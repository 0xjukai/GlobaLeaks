# -*- coding: utf-8 -*-

from twisted.internet import ssl

from OpenSSL import crypto, SSL
from OpenSSL.crypto import load_certificate, dump_certificate, load_privatekey, FILETYPE_PEM, TYPE_RSA, PKey, dump_certificate_request, X509Req, _new_mem_buf, _bio_to_string
from OpenSSL._util import lib as _lib, ffi as _ffi

from pyasn1.type import univ, constraint, char, namedtype, tag
from pyasn1.codec.der.decoder import decode

from globaleaks.models import Tenant
from globaleaks.models.config import PrivateFactory
from globaleaks.orm import transact


class ValidationException(Exception):
    pass


@transact
def tx_load_tls_dict(store, tid):
    # TODO rename to load_tls_dict
    return load_tls_dict(store, tid)


def load_tls_dict(store, tid):
    '''
    A quick and dirty function to grab all of the tls config for use in subprocesses
    '''
    privFact = PrivateFactory(store, tid)

    # /START ssl_* is used here to indicate the quality of the implementation
    # /END Tongue in cheek.
    tls_cfg = {
        'ssl_key': privFact.get_val('https_priv_key'),
        'ssl_cert': privFact.get_val('https_cert'),
        'ssl_intermediate': privFact.get_val('https_chain'),
        'ssl_dh': privFact.get_val('https_dh_params'),
        'https_enabled': privFact.get_val('https_enabled'),
        'commonname': Tenant.db_get(store, id=tid).https_hostname.split(':')[0],
        'tenant_id': tid,
    }

    return tls_cfg

def load_dh_params_from_string(ctx, dh_params_string):
    bio = _new_mem_buf()

    _lib.BIO_write(bio, str(dh_params_string), len(str(dh_params_string)))
    dh = _lib.PEM_read_bio_DHparams(bio, _ffi.NULL, _ffi.NULL, _ffi.NULL)
    dh = _ffi.gc(dh, _lib.DH_free)
    _lib.SSL_CTX_set_tmp_dh(ctx._context, dh)


def gen_dh_params(bits):
    dh = _lib.DH_new()
    _lib.DH_generate_parameters_ex(dh, bits, 2L, _ffi.NULL)

    bio = _new_mem_buf()
    _lib.PEM_write_bio_DHparams(bio, dh)
    return _bio_to_string(bio)


def gen_rsa_key(bits):
    """
    Generate an RSA key and returns it in PEM format.
    :rtype: An RSA key as an `pyopenssl.OpenSSL.crypto.PKey`
    """
    key = PKey()
    key.generate_key(TYPE_RSA, bits)

    return crypto.dump_privatekey(SSL.FILETYPE_PEM, key)


def gen_x509_csr(key_pair, csr_fields, csr_sign_bits):
    """
    gen_x509_csr creates a certificate signature request by applying the passed
    fields to the subject of the request, attaches the public key's fingerprint
    and signs the request using the private key.

    csr_fields dictionary and generates a
    certificate request using the passed keypair. Note that the default digest
    is sha256.

    :param key_pair: The key pair that will sign the request
    :type key_pair: :py:data:`OpenSSL.crypto.PKey` the key must have an attached
    private component.

    :param csr_fields: The certifcate issuer's details in X.509 Distinguished
    Name format.
    :type csr_fields: :py:data:`dict`
        C     - Country name
        ST    - State or province name
        L     - Locality name
        O     - Organization name
        OU    - Organizational unit name
        CN    - Common name
        emailAddress - E-mail address

    :rtype: A `pyopenssl.OpenSSL.crypto.X509Req`
    """
    req = X509Req()
    subj = req.get_subject()

    for field, value in csr_fields.iteritems():
        setattr(subj, field, value)

    prv_key = load_privatekey(SSL.FILETYPE_PEM, key_pair)

    req.set_pubkey(prv_key)
    req.sign(prv_key, 'sha'+str(csr_sign_bits))
    # TODO clean prv_key and str_prv_key from memory

    pem_csr = dump_certificate_request(SSL.FILETYPE_PEM, req)
    # TODO clean req from memory

    return pem_csr


def new_tls_context():
    # As discussed on https://trac.torproject.org/projects/tor/ticket/11598
    # there is no way to enable all TLS methods excluding SSL.
    # the problem lies in the fact that SSL.TLSv1_METHOD | SSL.TLSv1_1_METHOD | SSL.TLSv1_2_METHOD
    # is denied by OpenSSL.
    #
    # As spotted by nickm the only good solution right now is to enable SSL.SSLv23_METHOD then explicitly
    # use options: SSL_OP_NO_SSLv2 and SSL_OP_NO_SSLv3
    #
    # This trick make openssl consider valid all TLS methods.
    ctx = SSL.Context(SSL.SSLv23_METHOD)

    ctx.set_options(SSL.OP_NO_SSLv2 |
                    SSL.OP_NO_SSLv3 |
                    SSL.OP_NO_COMPRESSION |
                    SSL.OP_NO_TICKET |
                    SSL.OP_CIPHER_SERVER_PREFERENCE)

    ctx.set_mode(SSL.MODE_RELEASE_BUFFERS)

    cipher_list = bytes('ECDHE-RSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-SHA384:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-SHA256:ECDHE-RSA-AES256-SHA:DHE-DSS-AES256-SHA:DHE-RSA-AES128-SHA')
    ctx.set_cipher_list(cipher_list)

    return ctx


class TLSServerContextFactory(ssl.ContextFactory):
    def __init__(self, priv_key, certificate, intermediate, dh):
        """
        @param priv_key: String representation of the private key
        @param certificate: String representation of the certificate
        @param intermediate: String representation of the intermediate file
        @param dh: String representation of the DH parameters
        """
        self.ctx = new_tls_context()

        x509 = load_certificate(FILETYPE_PEM, certificate)
        self.ctx.use_certificate(x509)

        if intermediate != '':
            x509 = load_certificate(FILETYPE_PEM, intermediate)
            self.ctx.add_extra_chain_cert(x509)

        priv_key = load_privatekey(FILETYPE_PEM, priv_key)
        self.ctx.use_privatekey(priv_key)

        load_dh_params_from_string(self.ctx, dh)

        ecdh = _lib.EC_KEY_new_by_curve_name(_lib.NID_X9_62_prime256v1)
        ecdh = _ffi.gc(ecdh, _lib.EC_KEY_free)
        _lib.SSL_CTX_set_tmp_ecdh(self.ctx._context, ecdh)

    def getContext(self):
        return self.ctx


class CtxValidator(object):
    parents = []

    def _validate_parents(self, cfg, ctx):
        for parent in self.parents:
            p_v = parent()
            p_v._validate(cfg, ctx)

    def _validate(self, cfg, ctx):
        raise NotImplementedError()

    def validate(self, cfg, must_be_disabled=True):
        if must_be_disabled and cfg['https_enabled']:
            raise ValidationException('HTTPS must not be enabled')

        ctx = new_tls_context()
        try:
            self._validate_parents(cfg, ctx)
            self._validate(cfg, ctx)
        except Exception as err:
            return (False, err)
        return (True, None)


class PrivKeyValidator(CtxValidator):
    parents = []

    def _validate(self, cfg, ctx):
        raw_str = cfg['ssl_key']
        if raw_str == '':
            raise ValidationException('No private key is set')

        # Note that the empty string here prevents valid PKCS8 encrypted
        # keys from being used instead of plain pem keys.
        priv_key = load_privatekey(FILETYPE_PEM, raw_str, passphrase="")

        if priv_key.type() != TYPE_RSA or not priv_key.check():
            raise ValidationException('Invalid RSA key')


class CertValidator(CtxValidator):
    parents = [PrivKeyValidator]

    def _validate(self, cfg, ctx):
        certificate = cfg['ssl_cert']
        if certificate == '':
            raise ValidationException('There is no certificate')

        x509 = load_certificate(FILETYPE_PEM, certificate)

        # NOTE when a cert expires it will fail validation.
        if x509.has_expired():
            raise ValidationException('The certficate has expired')

        ctx.use_certificate(x509)

        priv_key = load_privatekey(FILETYPE_PEM, cfg['ssl_key'], passphrase='')

        ctx.use_privatekey(priv_key)

        # With the certificate loaded check if the key matches
        ctx.check_privatekey()

        if x509.get_subject().commonName != cfg['commonname']:
            #raise ValidationError('Configured hostname does not match commonname in certificate')
            pass

        # TODO according to RFC2818 best practice is to use SubjectAltName
        # https://tools.ietf.org/html/rfc2818.html#section-3.1



class ChainValidator(CtxValidator):
    parents = [PrivKeyValidator, CertValidator]

    def _validate(self, cfg, ctx):
        store = ctx.get_cert_store()

        intermediate = cfg['ssl_intermediate']
        if intermediate != '':
            x509 = load_certificate(FILETYPE_PEM, intermediate)

            if x509.has_expired():
                raise ValidationException('The intermediate cert has expired')

            store.add_cert(x509)
