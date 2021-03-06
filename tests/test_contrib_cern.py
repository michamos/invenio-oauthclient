# -*- coding: utf-8 -*-
#
# This file is part of Invenio.
# Copyright (C) 2016, 2017 CERN.
#
# Invenio is free software; you can redistribute it
# and/or modify it under the terms of the GNU General Public License as
# published by the Free Software Foundation; either version 2 of the
# License, or (at your option) any later version.
#
# Invenio is distributed in the hope that it will be
# useful, but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with Invenio; if not, write to the
# Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston,
# MA 02111-1307, USA.
#
# In applying this license, CERN does not
# waive the privileges and immunities granted to it by virtue of its status
# as an Intergovernmental Organization or submit itself to any jurisdiction.

"""Test case for CERN oauth remote app."""

from __future__ import absolute_import

from flask import g, session, url_for
from flask_security import login_user
from helpers import get_state, mock_remote_get, mock_response
from six.moves.urllib_parse import parse_qs, urlparse

from invenio_oauthclient.contrib.cern import account_info, \
    disconnect_handler, fetch_groups, get_dict_from_response


def test_fetch_groups(app, example_cern):
    """Test group extraction."""
    example_response, example_token, _ = example_cern
    res = get_dict_from_response(example_response)

    # Override hidden group configuration
    import re
    app.config['OAUTHCLIENT_CERN_HIDDEN_GROUPS'] = ('hidden_group',)
    app.config['OAUTHCLIENT_CERN_HIDDEN_GROUPS_RE'] = (
        re.compile(r'Group[1-3]'),
    )

    # Check that groups were hidden as required
    groups = fetch_groups(res['Group'])
    assert all(group in groups
               for group in ('Group{}'.format(i) for i in range(4, 6)))


def test_account_info(app, example_cern):
    """Test account info extraction."""
    client = app.test_client()
    ioc = app.extensions['oauthlib.client']

    # Ensure remote apps have been loaded (due to before first request)
    client.get(url_for('invenio_oauthclient.login', remote_app='cern'))

    example_response, _, example_account_info = example_cern

    mock_remote_get(ioc, 'cern', example_response)

    assert account_info(
        ioc.remote_apps['cern'], None) == example_account_info

    assert account_info(ioc.remote_apps['cern'], {}) == \
        dict(
            user=dict(
                email='test.account@cern.ch',
                profile={
                    'full_name': u'Test Account', 'username': u'taccount'
                },
            ),
            external_id='123456', external_method='cern',
            active=True
        )


def test_account_setup(app, example_cern, models_fixture):
    """Test account setup after login."""
    with app.test_client() as c:
        ioc = app.extensions['oauthlib.client']

        # Ensure remote apps have been loaded (due to before first request)
        resp = c.get(url_for('invenio_oauthclient.login', remote_app='cern'))
        assert resp.status_code == 302

        example_response, example_token, example_account_info = example_cern

        mock_response(app.extensions['oauthlib.client'], 'cern',
                      example_token)
        mock_remote_get(ioc, 'cern', example_response)

        resp = c.get(url_for(
            'invenio_oauthclient.authorized',
            remote_app='cern', code='test',
            state=get_state('cern')))
        assert resp.status_code == 302
        assert resp.location == ('http://localhost/account/settings/'
                                 'linkedaccounts/')
        assert len(g.identity.provides) == 7

    datastore = app.extensions['invenio-accounts'].datastore
    user = datastore.find_user(email='test.account@cern.ch')
    assert user

    with app.test_request_context():
        resp = disconnect_handler(ioc.remote_apps['cern'])
        assert resp.status_code >= 300

        login_user(user)
        assert len(g.identity.provides) == 7
        disconnect_handler(ioc.remote_apps['cern'])


def test_login(app):
    """Test CERN login."""
    client = app.test_client()

    resp = client.get(
        url_for('invenio_oauthclient.login', remote_app='cern',
                next='/someurl/')
    )
    assert resp.status_code == 302

    params = parse_qs(urlparse(resp.location).query)
    assert params['response_type'], ['code']
    assert params['scope'] == ['Name Email Bio Groups']
    assert params['redirect_uri']
    assert params['client_id']
    assert params['state']


def test_authorized_reject(app):
    """Test a rejected request."""
    with app.test_client() as c:
        c.get(url_for('invenio_oauthclient.login', remote_app='cern'))
        resp = c.get(
            url_for('invenio_oauthclient.authorized',
                    remote_app='cern', error='access_denied',
                    error_description='User denied access',
                    state=get_state('cern')))
        assert resp.status_code in (301, 302)
        assert resp.location == 'http://localhost/'
        # Check message flash
        assert session['_flashes'][0][0] == 'info'
