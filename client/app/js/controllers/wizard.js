GLClient.controller('WizardCtrl', ['$scope', '$location', '$route', '$http', 'Authentication', 'AdminUtils', 'CONSTANTS',
                    function($scope, $location, $route, $http, Authentication, AdminUtils, CONSTANTS) {
    $scope.email_regexp = CONSTANTS.email_regexp;

    $scope.step = 1;

    var finished = false;

    $scope.finish = function() {
      if (!finished) {
        $http.post('wizard', $scope.wizard).then(function() {
          Authentication.login('admin', $scope.wizard.admin.password, function() {
            $scope.reload("/admin/home");
          });
        });
      }
    };

    if ($scope.node.wizard_done) {
      /* if the wizard has been already performed redirect to the homepage */
      $location.path('/');
    } else {
      var receiver = AdminUtils.new_user();
      receiver.username = 'receiver';
      receiver.password = ''; // this causes the system to set the default password
                              // the system will then force the user to change the password
                              // at first login

      $scope.config_profiles = [
        {
          active: true,
          name:  'default',
          title: 'Use default settings',
        },
        {
          name:  'journo',
          title: 'Investigative journalism',
        },
        {
          name:  'transparency',
          title: 'NGO anticorruption reporting',
        },
        {
          name:  'public',
          title: 'Public administration compliant whistleblowing',
        },
        {
          name:  'corporate',
          title: 'Internal corporate fraud reporting',
        },
      ];

      $scope.selectProfile = function(profile) {
        angular.forEach($scope.config_profiles, function(p) {
          p.active = false;
        });
        profile.active = true;
        $scope.wizard.profile = profile.name;
      }

      var context = AdminUtils.new_context();

      $scope.wizard = {
        'node': {},
        'admin': {
          'mail_address': '',
          'password': ''
        },
        'receiver': receiver,
        'context': context
      };
    }
  }
]);
