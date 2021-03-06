import unittest
import time
import settings

from pymongo import MongoClient
import mongo
from mongo import ExperimentMongo
from data import StakoActivity, get_utc_timestamp, Experiment
import json

from api import app, Auth
ACTIVITY_TYPE_SO_VISIT = StakoActivity.ACTIVITY_TYPE_SO_VISIT
ACTIVITY_TYPE_SO_CLICK = StakoActivity.ACTIVITY_TYPE_SO_CLICK

URL = 'http://127.0.0.1:5000/v1/'
URL_ACTIVITY = URL + 'user/{}/activity/'
URL_EXPERIMENT = URL + 'user/{}/experiment/'


class TestAPI(unittest.TestCase):
	def setUp(self):
		settings.STAKO_TEST = True
		settings.MONGODB_NAME = settings.MONGODB_NAME_TEST
		settings.STAKO_EXPERIMENTS = {
			"test": ['group_a', 'group_b', 'control'],
			"test2": ['group2_a', 'group2_b', 'control']
		}
		# CLEAN DB
		client = MongoClient(settings.MONGODB_URL)
		db = client[settings.MONGODB_NAME_TEST]
		users = db[mongo.COLLECTION_USERS]
		users.drop()
		activities = db[mongo.COLLECTION_ACTIVITIES]
		activities.drop()
		experiment = db[mongo.COLLECTION_AUTH]
		experiment.drop()
		self.experiment_mongo = ExperimentMongo(settings)
		# ADD TEST USER
		self.tester_uuid = self.experiment_mongo.add_participant(Auth.TESTER_EMAIL)
		self.assertIsNotNone(self.tester_uuid)
		self.some_other_user_uuid = self.experiment_mongo.add_participant('not_authorized@stako.org')
		self.assertIsNotNone(self.some_other_user_uuid)


class TestAuthAPI(TestAPI):
	def test_auth(self):
		with app.test_client() as client:
			# NO EMAIL, NO GOOGLE_ID, NOR TOKEN
			response = client.get(URL + 'auth/')
			self.assertEqual(400, response.status_code)
			# INVALID EMAIL, GOOGLE_ID, AND TOKEN
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format('', '', ''))
			self.assertEqual(401, response.status_code)

			now = get_utc_timestamp()
			delta = settings.STAKO_JWT_TOKEN_EXPIRES
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format(Auth.TESTER_EMAIL, '', ''))
			self.assertEqual(200, response.status_code)
			auth_token = response.get_json()
			self.assertEqual(self.tester_uuid, auth_token['uuid'])
			self.assertRegex(auth_token['access_token'], '[a-zA-Z0-9-_]+?.[a-zA-Z0-9-_]+?.([a-zA-Z0-9-_]+)[/a-zA-Z0-9-_]+?$')
			self.assertTrue(isinstance(auth_token['expiration'], int))
			# This can fail by a second if the server call is at the moment where the second changes (1/1000 chance)?
			self.assertTrue(auth_token['expiration'] > 0)
			self.assertTrue(auth_token['expiration'] == now+delta or auth_token['expiration'] == now+delta-1)
			# TEST case non-sensitive email
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format(Auth.TESTER_EMAIL.upper(), '', ''))
			self.assertEqual(200, response.status_code)
			auth_token = response.get_json()
			self.assertEqual(self.tester_uuid, auth_token['uuid'])
			self.assertRegex(auth_token['access_token'], '[a-zA-Z0-9-_]+?.[a-zA-Z0-9-_]+?.([a-zA-Z0-9-_]+)[/a-zA-Z0-9-_]+?$')
			self.assertTrue(isinstance(auth_token['expiration'], int))


			# TODO: CREATE VALID EMAIL, GOOGLE_ID, AND TOKEN
			# TEST GET_USER
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid))
			self.assertEqual(401, response.status_code)
			header = {'Authorization': 'Bearer {}'.format(auth_token['access_token'])}
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=header)
			self.assertEqual(200, response.status_code)
			self.assertEqual(self.tester_uuid, response.get_json()['uuid'])

			# CATCH IMPERSONATION
			response = client.get(URL + 'user/{}/'.format(self.some_other_user_uuid), headers=header)
			self.assertEqual(403, response.status_code)

	def test_auth_expiration(self):
		app.config['JWT_ACCESS_TOKEN_EXPIRES'] = 1
		with app.test_client() as client:
			print('TOKEN EXPIRATION TIME: {}'.format(app.config['JWT_ACCESS_TOKEN_EXPIRES']))
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format(Auth.TESTER_EMAIL, '', ''))
			self.assertEqual(200, response.status_code)
			auth_token = response.get_json()
			self.assertEqual(self.tester_uuid, response.get_json()['uuid'])
			header = {'Authorization': 'Bearer {}'.format(auth_token['access_token'])}
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=header)
			self.assertEqual(200, response.status_code)
			self.assertEqual(self.tester_uuid, response.get_json()['uuid'])
			time.sleep(2)
			#TOKEN EXPIRED
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=header)
			self.assertEqual(401, response.status_code)


class TestUserAPI(TestAPI):
	def test_users_base(self):
		with app.test_client() as client:
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format(Auth.TESTER_EMAIL, '', ''))
			self.assertEqual(200, response.status_code)
			auth_token = response.get_json()
			self.header = {'Authorization': 'Bearer {}'.format(auth_token['access_token'])}

			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=self.header)
			self.assertEqual(200, response.status_code)
			self.assertEqual(self.tester_uuid, response.get_json()['uuid'])

			user = response.get_json()
			self.assertEqual(self.tester_uuid, user['uuid'])
			self.assertTrue('nickname' in user)
			self.assertFalse('email' in user)
			self.assertTrue('motto' in user)
			self.assertTrue('activity' in user)
			self.assertTrue('start_date' in user)

	def test_users_update(self):
		with app.test_client() as client:
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format(Auth.TESTER_EMAIL, '', ''))
			self.assertEqual(200, response.status_code)
			auth_token = response.get_json()
			header = {'Authorization': 'Bearer {}'.format(auth_token['access_token'])}
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=header)
			self.assertEqual(200, response.status_code)

			# CHANGING USER DATA
			user = response.get_json()
			user['nickname'] = 'Tester'
			user['motto'] = 'I will test it all!'
			user['uuid'] = 'SHOULD_NOT_BE_CHANGED'
			user['email'] = 'cannotadd@stako.org'
			# Does not make a difference
			user.pop('activity', None)

			response = client.put(URL + 'user/{}/'.format(self.tester_uuid), data=json.dumps(user),
								headers=header, content_type='application/json')
			self.assertEqual(200, response.status_code)
			# DID IT REALLY CHANGE?
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=header)
			self.assertEqual(200, response.status_code)
			user2 = response.get_json()
			self.assertEqual(self.tester_uuid, user2['uuid'])
			self.assertEqual(user['nickname'], user2['nickname'])
			self.assertEqual(user['motto'], user2['motto'])
			self.assertEqual(user['start_date'], user2['start_date'])
			self.assertTrue('activity' in user2)
			self.assertFalse('email' in user2)


class TestActivityAPI(TestAPI):
	def test_activity(self):
		with app.test_client() as client:
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format(Auth.TESTER_EMAIL, '', ''))
			self.assertEqual(200, response.status_code)
			auth_token = response.get_json()
			header = {'Authorization': 'Bearer {}'.format(auth_token['access_token'])}
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=header)
			self.assertEqual(200, response.status_code)

			# TODO: Test for all supported activity types!
			an_activity = {
				'url': 'https://stackoverflow.com/questions/20001229/',
				'type': ACTIVITY_TYPE_SO_VISIT
			}

			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(an_activity),
									headers=header, content_type='application/json')
			self.assertEqual(200, response.status_code)
			saved_activity = response.get_json()
			self.assertEqual(self.tester_uuid, saved_activity['uuid'])
			self.assertEqual(an_activity['url'], saved_activity['url'])
			self.assertEqual(ACTIVITY_TYPE_SO_VISIT, saved_activity['type'])

			# NO URL or TYPE
			a_bad_activity = {}
			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(a_bad_activity),
									headers=header, content_type='application/json')
			self.assertEqual(400, response.status_code)
			# BAD URL
			a_bad_activity = {'url': 'stackoverflow.com'}
			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(a_bad_activity),
									headers=header, content_type='application/json')
			self.assertEqual(400, response.status_code)
			# MISSING ACTIVITY "TYPE"
			a_bad_activity = an_activity.copy()
			a_bad_activity.pop('type', None)
			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(a_bad_activity),
								   headers=header, content_type='application/json')
			self.assertEqual(400, response.status_code)
			# NON-EXISTING ACTIVITY TYPE
			a_bad_activity['type'] = 'NOT_VALID'
			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(a_bad_activity),
								   headers=header, content_type='application/json')
			self.assertEqual(400, response.status_code)

			# TESTING CLICK TYPE
			# MISSING DATA FOR VALID TYPE
			another_activity = an_activity.copy()
			another_activity['type'] = ACTIVITY_TYPE_SO_CLICK
			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(another_activity),
								   headers=header, content_type='application/json')
			self.assertEqual(400, response.status_code)

			# FIXING FOR click TYPE
			another_activity['element'] = 'USER:1234'
			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(another_activity),
								   headers=header, content_type='application/json')
			self.assertEqual(200, response.status_code)

			# NO USER
			response = client.post(URL_ACTIVITY.format('SOME_BROKEN_UUID'), data=json.dumps(an_activity),
									headers=header, content_type='application/json')
			self.assertEqual(403, response.status_code)

			# TODO Only admin can act on other's account
			# self.assertEqual(403, response.status_code)

			# TESTING CLICK TYPE COMMING FROM POPUP
			# MISSING DATA FOR VALID TYPE
			another_activity = an_activity.copy()
			another_activity['url'] = 'https://www.stako.org/extensions/chrome'
			another_activity['type'] = ACTIVITY_TYPE_SO_CLICK
			another_activity['element'] = 'TAG:1234'
			response = client.post(URL_ACTIVITY.format(self.tester_uuid), data=json.dumps(another_activity),
								   headers=header, content_type='application/json')
			self.assertEqual(200, response.status_code)


class TestExperimentAPI(TestAPI):

	def setUp(self):
		super(TestExperimentAPI, self).setUp()
		added = self.experiment_mongo.add_participant_experiment(Auth.TESTER_EMAIL, 'test', 'control')
		self.assertTrue(added)
		added = self.experiment_mongo.add_participant_experiment(Auth.TESTER_EMAIL, 'test2', 'group2_a')
		self.assertTrue(added)
		self.exp_name_test_hash = Experiment._hash_string('test')
		self.exp_group_test_hash = Experiment._hash_string('control')
		self.exp_name_test2_hash = Experiment._hash_string('test2')
		self.exp_group_test2_hash = Experiment._hash_string('group2_a')

	def test_experiments(self):
		with app.test_client() as client:
			response = client.get(URL + 'auth/?email={}&google_id={}&token={}'.format(Auth.TESTER_EMAIL, '', ''))
			self.assertEqual(200, response.status_code)
			auth_token = response.get_json()
			header = {'Authorization': 'Bearer {}'.format(auth_token['access_token'])}
			response = client.get(URL + 'user/{}/'.format(self.tester_uuid), headers=header)
			self.assertEqual(200, response.status_code)
			# GET NON-EXISTENT PARTICIPANT
			response = client.get(URL_EXPERIMENT.format('NOT_VALID_USERID'), headers=header,
								  content_type='application/json')
			self.assertEqual(403, response.status_code)
			# VALID USER
			response = client.get(URL_EXPERIMENT.format(self.tester_uuid), headers=header,
								  content_type='application/json')
			self.assertEqual(200, response.status_code)
			u_experiments = response.get_json()
			self.assertEqual(self.tester_uuid, u_experiments['uuid'])
			self.assertEqual(2, len(u_experiments['experiments']))
			self.assertTrue(self.exp_name_test_hash in u_experiments['experiments'].keys())
			self.assertTrue(self.exp_name_test2_hash in u_experiments['experiments'].keys())
			self.assertEqual(self.exp_group_test_hash, u_experiments['experiments'][self.exp_name_test_hash])
			self.assertEqual(self.exp_group_test2_hash, u_experiments['experiments'][self.exp_name_test2_hash])
