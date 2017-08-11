import SimpleHTTPServer
import SocketServer
import gzip, json, os, signal, ssl, tempfile, time, urllib2
from StringIO import StringIO

from twisted.internet import threads, reactor
from twisted.internet.defer import inlineCallbacks, Deferred

from globaleaks.models.config import PrivateFactory, load_tls_dict
from globaleaks.utils.sock import reserve_port_for_ip
from globaleaks.orm import transact
from globaleaks.workers import supervisor, process
from globaleaks.workers.worker_https import HTTPSProcess

from globaleaks.tests import helpers, TEST_DIR
from globaleaks.tests.utils import test_tls

@transact
def toggle_https(store, enabled):
    PrivateFactory(store).set_val('https_enabled', enabled)

class TestProcessSupervisor(helpers.TestGL):
    @inlineCallbacks
    def setUp(self):
        super(TestProcessSupervisor, self).setUp()
        ssl._https_verify_certificates(enable=False)
        yield test_tls.commit_valid_config()

    @inlineCallbacks
    def test_init_with_no_launch(self):
        yield toggle_https(enabled=False)
        sock, fail = reserve_port_for_ip('127.0.0.1', 43434)
        self.assertIsNone(fail)

        ip, port = '127.0.0.1', 43435

        p_s = supervisor.ProcessSupervisor([sock], ip, port)
        yield p_s.maybe_launch_https_workers()

        self.assertFalse(p_s.is_running())

        yield p_s.shutdown()

        self.assertFalse(p_s.shutting_down)
        self.assertFalse(p_s.is_running())

    @inlineCallbacks
    def test_init_with_launch(self):
        yield toggle_https(enabled=True)
        self.https_sock, fail = reserve_port_for_ip('127.0.0.1', 43434)
        self.assertIsNone(fail)

        ip, proxy_port = '127.0.0.1', 43435

        print 'https_sock', self.https_sock
        p_s = supervisor.ProcessSupervisor([self.https_sock], ip, proxy_port)
        yield p_s.maybe_launch_https_workers()

        self.assertTrue(p_s.is_running())
        self.assertTrue(p_s.tls_process_pool > 0)

        self.pp = helpers.SimpleServerPP()

        script_path = os.path.abspath(os.path.join(TEST_DIR, 'subprocs', 'slow_server.py'))
        reactor.spawnProcess(self.pp, 'python',
                             args=['python', script_path, str(proxy_port)],
                             usePTY=True)

        yield self.pp.start_defer

        yield threads.deferToThread(self.fetch_resource)

        #from IPython.core.debugger import Tracer; Tracer()()

        # TODO ensure that the reactor goes down
        d = threads.deferToThread(self.fetch_resource)

        #from globaleaks.utils.utility import deferred_sleep
        #yield deferred_sleep(1)

        yield p_s.shutdown()

        self.assertFalse(p_s.shutting_down)
        self.assertFalse(p_s.is_running())

    def tearDown(self):
        self.https_sock.close()
        #if hasattr(self, 'pp'):
        #    self.pp.transport.loseConnection()
        #    self.pp.transport.signalProcess('KILL')

        helpers.TestGL.tearDown(self)

    def fetch_resource(self):
        response = urllib2.urlopen('https://127.0.0.1:43434')
        hdrs = response.info()
        self.assertEqual(hdrs.get('Server'), 'SimpleHTTP/0.6 Python/2.7.12')


@transact
def wrap_db_tx(store, f, *args, **kwargs):
    return f(store, *args, **kwargs)

class TestSubprocessRun(helpers.TestGL):

    @inlineCallbacks
    def setUp(self):
        super(TestSubprocessRun, self).setUp()

        with open('hello.txt', 'w') as f:
            f.write('Hello, world!\n')

        https_sock, _ = reserve_port_for_ip('127.0.0.1', 9443)
        self.https_socks = [https_sock]
        ssl._https_verify_certificates(enable=False)
        yield test_tls.commit_valid_config()

    @inlineCallbacks
    def test_https_process(self):
        valid_cfg = {
            'proxy_ip': '127.0.0.1',
            'proxy_port': 43434,
            'tls_socket_fds': [sock.fileno() for sock in self.https_socks],
            'debug': False,
        }
        db_cfg = yield wrap_db_tx(load_tls_dict)
        valid_cfg.update(db_cfg)

        tmp = tempfile.TemporaryFile()
        tmp.write(json.dumps(valid_cfg))
        tmp.seek(0,0)
        tmp_fd = tmp.fileno()

        self.http_process = HTTPSProcess(fd=tmp_fd)

        # Connect to service ensure that it responds with a 502
        yield threads.deferToThread(self.fetch_resource_with_fail)

        # Start the HTTP server proxy requests will be forwarded to.
        self.pp = helpers.SimpleServerPP()
        reactor.spawnProcess(self.pp, 'python',
                             args=['python', '-m', 'SimpleHTTPServer', '43434'],
                             usePTY=True)

        yield self.pp.start_defer

        # Check that requests are routed successfully
        yield threads.deferToThread(self.fetch_resource)
        yield threads.deferToThread(self.fetch_resource_with_gzip)

    def fetch_resource_with_fail(self):
        try:
            response = urllib2.urlopen('https://127.0.0.1:9443')
            self.fail('Request had to throw a 502')
        except urllib2.HTTPError as e:
            # Ensure the connection always has an HSTS header
            self.assertEqual(e.headers.get('Strict-Transport-Security'), 'max-age=31536000')
            self.assertEqual(e.code, 502)
            return

    def fetch_resource(self):
        response = urllib2.urlopen('https://127.0.0.1:9443/')
        hdrs = response.info()
        self.assertEqual(hdrs.get('Strict-Transport-Security'), 'max-age=31536000')

    def fetch_resource_with_gzip(self):
        request = urllib2.Request('https://127.0.0.1:9443/hello.txt')
        request.add_header('Accept-encoding', 'gzip')
        response = urllib2.urlopen(request)
        hdrs = response.info()

        # Ensure the connection uses gzip
        self.assertEqual(hdrs.get('Content-Encoding'), 'gzip')

        s = response.read()
        buf = StringIO(s)
        f = gzip.GzipFile(fileobj=buf)
        data = f.read()

        self.assertEqual(data, 'Hello, world!\n')

    def tearDown(self):
        for sock in self.https_socks:
            sock.close()

        if hasattr(self, 'http_process'):
            self.http_process.shutdown()
        if hasattr(self, 'pp'):
            self.pp.transport.loseConnection()
            self.pp.transport.signalProcess('KILL')

        helpers.TestGL.tearDown(self)
