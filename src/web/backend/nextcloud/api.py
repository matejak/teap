from flask import Blueprint, jsonify, request, abort, current_app
from flask.views import MethodView

from nextcloud import NextCloud

blueprint = Blueprint('nextcloud_api', __name__, url_prefix='/api')

ALLOWED_GROUP_TYPES = ['divisions', 'countries', 'other']


class NextCloudMixin:

    @property
    def nextcloud(self):
        """ Get nextcloud instance """
        # TODO move to singleton global object
        url = current_app.config['NEXTCLOUD_HOST']
        username = current_app.config['NEXTCLOUD_USER']
        password = current_app.config['NEXTCLOUD_PASSWORD']
        if url is None or username is None or password is None:
            return abort(400)
        nxc = NextCloud(endpoint=url, user=username, password=password)
        return nxc

    def nxc_response(self, nextcloud_response):
        return jsonify({
            'status': nextcloud_response.is_ok,
            'message': nextcloud_response.meta.get('message', ''),
            'data': nextcloud_response.data
            })


class UserViewSet(NextCloudMixin,
                  MethodView):

    def get(self, username=None):
        """ List users """
        if username is None:
            res = self.nextcloud.get_users()
            return self.nxc_response(res)
        else:
            res = self.nextcloud.get_user(username)
            return self.nxc_response(res)

    def post(self):
        """ Create user """
        username = request.json.get('username')
        password = request.json.get('password')
        groups = request.json.get('groups', [])
        if not all([username, password]):
            return abort(400)
        res = self.nextcloud.add_user(username, password)
        for group in groups:
            self.nextcloud.add_to_group(username, group)
        return self.nxc_response(res), 201

    def delete(self, username):
        """ Delete user """
        res = self.nextcloud.delete_user(username)
        return self.nxc_response(res)

    def patch(self, username, action=None):
        if action is not None:
            if action not in ['enable', 'disable']:
                return jsonify({}), 404
            res = self.nextcloud.enable_user(username) if action == 'enable' else self.nextcloud.disable_user(username)
            return self.nxc_response(res)
        param = request.json.get('param')
        value = request.json.get('value')
        if not all([param, value]):
            return jsonify({}), 400
        res = self.nextcloud.edit_user(username, param, value)
        return self.nxc_response(res)


class UserGroupViewSet(NextCloudMixin,
                       MethodView):

    def post(self, username):
        """ Add user to group """
        group_name = request.json.get('group_name')
        if not group_name:
            return abort(400)
        if not self.nextcloud.get_group(group_name).is_ok:
            return jsonify({"message": "group not found"}), 404
        res = self.nextcloud.add_to_group(username, group_name)
        return self.nxc_response(res)

    def delete(self, username, group_name):
        """ Remove user from group """
        res = self.nextcloud.remove_from_group(username, group_name)
        return self.nxc_response(res)


class GroupViewSet(NextCloudMixin,
                   MethodView):

    def get(self, group_name=None, action=None):
        """ List groups """
        if group_name is None and action is None:
            res = self.nextcloud.get_groups()
            return self.nxc_response(res)
        elif group_name and action is None:
            res = self.nextcloud.get_group(group_name)
            return self.nxc_response(res)
        elif group_name and action == "subadmins":
            res = self.nextcloud.get_subadmins(group_name)
            return self.nxc_response(res)
        else:
            return abort(400)

    def post(self, group_name=None):
        """ Create group """
        if group_name:  # create subadmin
            username = request.json.get('username')
            if not username:
                return abort(400)
            if not self.nextcloud.get_group(group_name).is_ok:
                return jsonify({"message": "group not found"}), 404
            res = self.nextcloud.create_subadmin(username, group_name)
            return self.nxc_response(res), 201
        else:  # create group
            group_name = request.json.get('group_name')
            if not group_name:
                return abort(400)
            res = self.nextcloud.add_group(group_name)
            return self.nxc_response(res), 201

    def delete(self, group_name, username=None):
        """ Delete group """
        if username:  # delete subadmin
            if not self.nextcloud.get_group(group_name).is_ok:
                return jsonify({"message": "group not found"}), 404
            res = self.nextcloud.remove_subadmin(username, group_name)
            return self.nxc_response(res), 201
        else:
            res = self.nextcloud.delete_group(group_name)
            return self.nxc_response(res), 202


class GroupWithFolderViewSet(NextCloudMixin, MethodView):

    def post(self):
        group_name = request.json.get('group_name')
        group_type = request.json.get('group_type')

        if not group_name or not group_type:  # check if all params present
            return abort(400)

        if group_type.lower() not in ALLOWED_GROUP_TYPES:  # check if group type in list of allowed types
            return jsonify({"message": "Not allowed group type"}), 400

        if self.nextcloud.get_group(group_name).is_ok:  # check if group with such name doesn't exist
            return jsonify({"message": "Group with this name already exists"}), 400

        create_group_res = self.nextcloud.add_group(group_name)  # create group
        if not create_group_res.is_ok:
            return jsonify({"message": "Something went wrong during group creation"}), 400

        create_folder_res = self.nextcloud.create_group_folder("/".join([group_type, group_name]))  # create folder
        if not create_folder_res.is_ok:
            self.nextcloud.delete_group(group_name)
            return jsonify({"message": "Something went wrong during group folder creation"}), 400

        return jsonify({"message": "Group with group folder successfully created"}), 201


user_view = UserViewSet.as_view('users_api')
blueprint.add_url_rule('/users/', view_func=user_view, methods=['GET', 'POST'])
blueprint.add_url_rule('/users/<username>', view_func=user_view, methods=['GET', 'DELETE'])
blueprint.add_url_rule('/users/<username>', view_func=user_view, methods=['PATCH'])
blueprint.add_url_rule('/users/<username>/<action>', view_func=user_view, methods=['PATCH'])

user_group_view = UserGroupViewSet.as_view('user_groups_api')
blueprint.add_url_rule('/users/<username>/groups/', view_func=user_group_view, methods=['POST'])
blueprint.add_url_rule('/users/<username>/groups/<group_name>', view_func=user_group_view, methods=['DELETE'])

group_view = GroupViewSet.as_view('groups_api')
blueprint.add_url_rule('/groups/', view_func=group_view, methods=["GET", "POST"])
blueprint.add_url_rule('/groups/<group_name>', view_func=group_view, methods=["GET", "DELETE"])
blueprint.add_url_rule('/groups/<group_name>/<action>', view_func=group_view, methods=["GET"])
blueprint.add_url_rule('/groups/<group_name>/subadmins', view_func=group_view, methods=["POST", "DELETE"])
blueprint.add_url_rule('/groups/<group_name>/subadmins/<username>', view_func=group_view, methods=["DELETE"])

group_with_folder_view = GroupWithFolderViewSet.as_view('groups_with_folder_api')
blueprint.add_url_rule('/groups-with-folders', view_func=group_with_folder_view, methods=["POST"])
