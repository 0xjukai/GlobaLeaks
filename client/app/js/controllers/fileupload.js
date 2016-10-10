GLClient.controller('WBFileUploadCtrl', ['$scope', '$q', '$timeout', 'loadingModal', 'handleRejectOp', 'glbcWhistleblower', function($scope, $q, $timeout, loadingModal, handleRejectOp, glbcWhistleblower)  {
  var disabled = false;
  $scope.isDisabled = function() {
    return disabled || !glbcWhistleblower.variables.keyDerived;
  };

  $scope.$on('flow::fileAdded', function (event, flow, file) {
    if (file.size > $scope.node.maximum_filesize * 1024 * 1024) {
      file.error = true;
      file.error_msg = "This file exceeds the maximum upload size for this server.";
      // TODO debug file.error_msg it is misbehaving
      handleRejectOp.show("fileUpload", file.error_msg);
      event.preventDefault();
    } else {
      if ($scope.field !== undefined && !$scope.field.multi_entry) {
        // if the field allows to load only one file disable the button
        // as soon as a file is loaded.
       disabled = true;
      }
    }

    if (file.file.encrypted === undefined) {
      event.preventDefault();
      loadingModal.show();
      glbcWhistleblower.handleFileEncryption(file.file)
      .then(function(outputFile) {
        outputFile.encrypted = true;
        outputFile.name = file.name;
        $timeout(function() {
          flow.addFile(outputFile);
        }, 0);
      }, function(err) {
        handleRejectOp.show("fileUpload", err);
      }).finally(function() {
        loadingModal.hide();
      });
    }
  });
}]).
controller('ImageUploadCtrl', ['$scope', '$rootScope', '$http', function($scope, $rootScope, $http) {
  $scope.imgDataUri = $scope.$parent.imgDataUri;

  $scope.imageUploadObj = {};
  $scope.Authentication = $rootScope.Authentication;
  $scope.Utils = $rootScope.Utils;

  $scope.deletePicture = function() {
    $http({
      method: 'DELETE',
      url: $scope.imageUploadUrl,
      headers: $scope.Authentication.get_auth_headers()
    }).then(function successCallback() {
      $scope.imageUploadModel[$scope.imageUploadModelAttr] = '';
      $scope.imageUploadObj.flow.files = [];
    }, function errorCallback() { });
  };
}]);
