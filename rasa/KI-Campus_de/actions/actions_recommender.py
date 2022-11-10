from enum import auto
from typing import Text, Dict, Any, List, Optional

from rasa_sdk import Action, Tracker
from rasa_sdk.events import SlotSet

import requests
import json

from rasa_sdk import FormValidationAction
from rasa_sdk.executor import CollectingDispatcher
from rasa_sdk.events import Restarted
from rasa_sdk.types import DomainDict

from .settings import get_recommender_config
from .responses import get_response_texts, assert_responses_exist, ResponseEnum, get_response, ActionResponsesFiles


class ActionRestart(Action):

	def name(self) -> Text:
		return "action_restart"

	async def run(
		self, dispatcher, tracker: Tracker, domain: Dict[Text, Any]
	) -> List[Dict[Text, Any]]:

		# custom behavior
		dispatcher.utter_message(response="utter_restart")

		return [Restarted()]


class ActionCheckLogin(Action):

	def name(self) -> Text:
		return "action_check_login"

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		current_state = tracker.current_state()
		is_logged_in = tracker.get_slot('user_login')
		if is_logged_in:
			print('ActionCheckLogin[sender_id="{0}"]: ALREADY LOGGED IN, User ID {1}'.format(current_state['sender_id'], tracker.get_slot('user_id')), '\n')  # FIXME DEBUG
			return []

		token = current_state['sender_id']
		r = requests.get('https://learn.ki-campus.org/bridges/chatbot/user',
						 headers={
							 "content-type": "application/json",
							 "Authorization": 'Bearer {0}'.format(token)
						 })
		status = r.status_code

		print('ActionCheckLogin[sender_id="{0}"]: status_code '.format(token), r.status_code, ', headers: ', r.headers, ', content: ', json.loads(r.content), '\n')  # FIXME DEBUG

		if status == 200:
			response = json.loads(r.content)
			user_id: Optional[str] = None
			if 'id' in response:  # FIXME use SAML ID when available
				user_id = response['id']
			return [SlotSet("user_login", True), SlotSet("user_id", user_id)]
		# elif status == 401:  # Status-Code 401 not authorized

		return [SlotSet("user_login", False), SlotSet("user_id", None)]


class ActionFetchProfile(Action):

	def name(self) -> Text:
		return "action_fetch_profile"

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		enrollments: Optional[List[any]] = None
		current_state = tracker.current_state()
		token = current_state['sender_id']
		r = requests.get('https://learn.ki-campus.org/bridges/chatbot/my_courses',
						 headers={
							 "content-type": "application/json",
							 "Authorization": 'Bearer {0}'.format(token)
						 })
		status = r.status_code
		if status == 200:
			response = json.loads(r.content)
			if len(response) < 1:
				enrollments = []
			else:
				# for course in response:
				# 	enrollments.append(course)
				enrollments = response  # TODO [russa] only store part of data? e.g. only the ID or course_code?
		# elif status == 401:  # Status-Code 401 not authorized
		# 	enrollments = None
		# else:  # Other Stati
		# 	enrollments = None

		# FIXME TEST values:
		# TODO for these, would need to query KIC endpoint https://ki-campus.org/kic_api/users/<kic user id>
		course_visits = ["Big Data Analytics"]
		search_terms = ["KI", "Machine Learning"]
		print('ActionFetchProfile: enrollments ', enrollments, ' | course_visits ', course_visits, ' | search_terms ', search_terms, '\n')  # FIXME DEBUG

		return [SlotSet("enrollments", enrollments), SlotSet("course_visits", course_visits), SlotSet("search_terms", search_terms)]

######################################################################################
# RECOMMENDER
######################################################################################


class ActionGetLearningRecommendation(Action):
	class Responses(ResponseEnum):
		no_recommendations_found = auto()
		found_recommendations = auto()
		"""
		text found_recommendations has 1 parameter: 
        * parameter {0}: total number (int) of found course recommendations
		"""
		found_recommendations_single = auto()
		"""
		text found_recommendations_single has 1 parameter: 
        * parameter {0}: total number (int) of found course recommendations
		"""
		found_course_item = auto()
		"""
		text found_course_item has 2 parameters:
        * parameter {0}: the title of the course
        * parameter {1}: the URL-parameter /-ID for the course
		"""
		found_recommendations_more_single = auto()
		"""
		text found_recommendations_more_single has 1 parameter:
        * parameter {0}: number (int) of found, additional course recommendations (that are not shown yet)
		"""
		found_recommendations_more_multiple = auto()
		"""
		text found_recommendations_more_multiple has 1 parameter:
        * parameter {0}: number (int) of found, additional course recommendations (that are not shown yet)
		"""
		error_401 = auto()
		error_404 = auto()
		error_500 = auto()
		error_unknown = auto()
		"""
		text error_unknown has 1 parameter:
        * parameter {0}: the (text) content of the error message
		"""
		debug_error = auto()
		"""
		text debug_error has 3 parameters:
        * parameter {0}: the (HTTP) status code of the error message
        * parameter {1}: the (HTTP) headers of the error message
        * parameter {2}: the body/content of (HTTP) error message
		"""
		debug_recommendation_parameters = auto()
		"""
		text debug_recommendation_parameters has 1 parameter:
        * parameter {0}: string/description for the course recommendation/filter parameters
		"""

	responses: Dict[str, str]

	service_url: str
	service_token: str

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

		# NOTE will print error message if file or fields are missing:
		recommender_config = get_recommender_config()
		self.service_url = recommender_config['url']
		self.service_token = recommender_config['token']

		# FIXME DEBUG output TODO remove after testing
		if recommender_config and recommender_config['url'] and recommender_config['token']:
			print("\n  endpoint config: {0}\n".format(recommender_config))
		else:
			print("\n  endpoint config: NO CONFIGURATION FOR RECOMMENDER (recommender_api)\n")

	def name(self) -> Text:
		return "action_get_learning_recommendation"

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		language = str(tracker.get_slot("language"))
		topic = str(tracker.get_slot("topic"))
		level = str(tracker.get_slot("level"))
		max_duration_str = tracker.get_slot("max_duration")  # int(tracker.get_slot("max_duration"))
		certificate = str(tracker.get_slot("certificate"))
		enrollments = tracker.get_slot("enrollments")
		course_visits = tracker.get_slot("course_visits")
		search_terms = tracker.get_slot("search_terms")

		if enrollments:
			enrollments = [course['id'] for course in enrollments]  # TODO use course_code instead of id when available?

		# to do: maybe option 2 implement after delete slot value

		# FIXME DEBUG: show search/filter parameters
		debug_info_msg = "\n  language {0} | topic {1} | level {2} | max_duration {3} | certificate {4} | " \
						 "enrollments {5} | course_visits {6} | search_terms {7}\n".format(
							language, topic, level, max_duration_str, certificate, enrollments, course_visits, search_terms
						 )
		debug_params = get_response(self.responses, self.Responses.debug_recommendation_parameters).format(debug_info_msg)
		dispatcher.utter_message(text=debug_params)

		r = requests.get('{0}filtered_recommendation_learnings/'.format(self.service_url),
			headers={
				"content-type": "application/json",
				"Authorization": 'Token {0}'.format(self.service_token),
			},
			params={
				"language": language,
				"topic": topic,
				"level": level,
				"max_duration": max_duration_str,  # str(max_duration),
				"certificate": certificate,
				"enrollments": enrollments,
				"course_visits": course_visits,
				"search_terms": search_terms,
			})
		status = r.status_code
		response: Optional[List] = None
		if status == 200:
			response = json.loads(r.content)
			if len(response) < 1:
				dispatcher.utter_message(get_response(self.responses, self.Responses.no_recommendations_found))
			else:
				size = len(response)
				limit = min(size, 3)
				dispatcher.utter_message(get_response(self.responses, self.Responses.found_recommendations_single).format(size)) if size == 1 else dispatcher.utter_message(get_response(self.responses, self.Responses.found_recommendations).format(size))
				course_label = get_response(self.responses, self.Responses.found_course_item)
				button_group = []
				for course in response[0:limit]:
					title = course['name']
					url_param = course['id']  # FIXME use course_code when available & create URL for displaying course's website
					# dispatcher.utter_message(text="* [{0}](https://ki-campus.org/course/{1})".format(title, url_param))
					button_group.append({"title": course_label.format(title, url_param), "payload": '{0}'.format(title)})
				dispatcher.utter_message(text=" ", buttons=button_group)  # FIXME non-empty message as WORKAROUND for BUG in socketio-adapter (rasa v3.0-v3.2)

				if limit < size:
					rest = size - limit
					msg_type = self.Responses.found_recommendations_more_single if rest == 1 else self.Responses.found_recommendations_more_multiple
					dispatcher.utter_message(get_response(self.responses, msg_type).format(rest))

		elif status == 401:  # Status-Code 401 Unauthorized: wrong access token setting in kic_recommender.yml!
			dispatcher.utter_message(get_response(self.responses, self.Responses.error_401))
			# FIXME DEBUG:
			dispatcher.utter_message(get_response(self.responses, self.Responses.debug_error).format(str(r.status_code), str(r.headers), str(r.content)))
		elif status == 404:  # Status-Code 404 None
			dispatcher.utter_message(get_response(self.responses, self.Responses.error_404))
			# FIXME DEBUG:
			dispatcher.utter_message(get_response(self.responses, self.Responses.debug_error).format(str(r.status_code), str(r.headers), str(r.content)))
		elif status == 500:  # Status-Code 500 Invalid Parameter
			dispatcher.utter_message(get_response(self.responses, self.Responses.error_500))
			# FIXME DEBUG:
			dispatcher.utter_message(get_response(self.responses, self.Responses.debug_error).format(str(r.status_code), str(r.headers), str(r.content)))
		else:
			dispatcher.utter_message(get_response(self.responses, self.Responses.error_unknown).format(str(r.content)))
			# FIXME DEBUG:
			dispatcher.utter_message(get_response(self.responses, self.Responses.debug_error).format(str(r.status_code), str(r.headers), str(r.content)))

		return [SlotSet("recommendations", response)]


class ActionAdditionalLearningRecommendation(Action):
	class Responses(ResponseEnum):
		no_more_recommendations = auto()
		additional_recommendations = auto()
		"""
		text additional_recommendations has 1 parameter:
        * parameter {0}: total number (int) of additional (not yet displayed) course recommendations
		"""
		additional_recommendations_single = auto()
		"""
		text additional_recommendations_single has 1 parameter:
        * parameter {0}: total number (int) of additional (not yet displayed) course recommendations
		"""
		additional_course_item = auto()
		"""
		text additional_course_item has 2 parameters:
        * parameter {0}: the title of the course
        * parameter {1}: the URL-parameter /-ID for the course
		"""
		additional_recommendations_more_single = auto()
		"""
		text additional_recommendations_more_single has 1 parameter:
        * parameter {0}: number (int) of found, additional course recommendations (that are not shown yet)
		"""
		additional_recommendations_more_multiple = auto()
		"""
		text additional_recommendations_more_multiple has 1 parameter:
        * parameter {0}: number (int) of found, additional course recommendations (that are not shown yet)
		"""

	responses: Dict[str, str]

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

	def name(self) -> Text:
		return "action_additional_learning_recommendation"

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		recommendations = tracker.get_slot("recommendations")
		if not recommendations or len(recommendations) <= 3:
			dispatcher.utter_message(get_response(self.responses, self.Responses.no_more_recommendations))
		else:
			recommendations = recommendations[3:]
			size = len(recommendations)
			limit = min(size, 3)
			dispatcher.utter_message(get_response(self.responses, self.Responses.additional_recommendations_single).format(size)) if size == 1 else dispatcher.utter_message(get_response(self.responses, self.Responses.additional_recommendations).format(size))
			course_label = get_response(self.responses, self.Responses.additional_course_item)
			button_group = []
			for course in recommendations[0:limit]:
				title = course['name']
				url_param = course['id']  # FIXME use course_code when available & create URL for displaying course's website
				button_group.append({"title": course_label.format(title, url_param), "payload": '{0}'.format(title)})
			dispatcher.utter_message(text=" ", buttons=button_group)  # FIXME non-empty message as WORKAROUND for BUG in socketio-adapter (rasa v3.0-v3.2)

			if limit < size:
				rest = size - limit
				msg_type = self.Responses.additional_recommendations_more_single if rest == 1 else self.Responses.additional_recommendations_more_multiple
				dispatcher.utter_message(get_response(self.responses, msg_type).format(rest))

		return [SlotSet("recommendations", recommendations)]

##########################################################################################
# FORMS & SLOTS
##########################################################################################


class ActionDeleteSlotValue(Action):
	def name(self):
		return 'action_delete_slot_value'

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		# check intent then delete slot	value
		intent = str(tracker.get_intent_of_latest_message())
		print(f"{intent}")  # FIXME DEBUG to do: delete - checking function
		if  intent == 'change_language_slot': return [SlotSet("language", None)]
		elif  intent == 'change_topic_slot': return [SlotSet("topic", None)]
		elif  intent == 'change_level_slot': return [SlotSet("level", None)]
		elif  intent == 'change_max_duration_slot': return [SlotSet("max_duration", None)]
		elif  intent == 'change_certificate_slot': return [SlotSet("certificate", None)]
		elif  intent == 'start_recommender_form': return [SlotSet("language", None), SlotSet("topic", None), SlotSet("level", None), SlotSet("max_duration", None), SlotSet("certificate", None)]
		else:  return []


class ActionAskLanguage(Action):
	class Responses(ResponseEnum):
		confirm_and_show_change_language = auto()
		ask_select_language = auto()
		language_option_german = auto()
		language_option_english = auto()
		language_option_any = auto()

	responses: Dict[str, str]

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

	def name(self):
		return 'action_ask_language'

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		buttons = [
			{'title': get_response(self.responses, self.Responses.language_option_german), 'payload': '/inform{"language":"Deutsch"}'},
			{'title': get_response(self.responses, self.Responses.language_option_english), 'payload': '/inform{"language":"Englisch"}'},
			{'title': get_response(self.responses, self.Responses.language_option_any), 'payload': '/undecided'}]

		# check if slot value should get changed
		intent = str(tracker.get_intent_of_latest_message())
		if intent == 'change_language_slot':
			text = get_response(self.responses, self.Responses.confirm_and_show_change_language)
		# default question
		else:
			text = get_response(self.responses, self.Responses.ask_select_language)

		dispatcher.utter_message(text=text, buttons=buttons)
		return []


class ActionAskTopic(Action):
	class Responses(ResponseEnum):
		confirm_and_show_change_topic = auto()
		ask_select_topic = auto()
		topic_option_introduction_ai = auto()
		topic_option_specialized_ai = auto()
		topic_option_professions_and_ai = auto()
		topic_option_society_and_ai = auto()
		topic_option_data_science = auto()
		topic_option_machine_learning = auto()
		topic_option_any = auto()

	responses: Dict[str, str]

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

	def name(self):
		return 'action_ask_topic'

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		buttons = [
			{'title': get_response(self.responses, self.Responses.topic_option_introduction_ai), 'payload': '/inform{"topic":"ki-einführung"}'},
			{'title': get_response(self.responses, self.Responses.topic_option_specialized_ai), 'payload': '/inform{"topic":"ki-vertiefung"}'},
			{'title': get_response(self.responses, self.Responses.topic_option_professions_and_ai), 'payload': '/inform{"topic":"ki-berufsfelder"}'},
			{'title': get_response(self.responses, self.Responses.topic_option_society_and_ai), 'payload': '/inform{"topic":"ki-gesellschaft"}'},
			{'title': get_response(self.responses, self.Responses.topic_option_data_science), 'payload': '/inform{"topic":"Data Science"}'},
			{'title': get_response(self.responses, self.Responses.topic_option_machine_learning), 'payload': '/inform{"topic":"Maschinelles Lernen"}'},
			{'title': get_response(self.responses, self.Responses.topic_option_any), 'payload': '/undecided'}]

		intent = str(tracker.get_intent_of_latest_message())
		if intent == 'change_topic_slot':
			text = get_response(self.responses, self.Responses.confirm_and_show_change_topic)
		else:
			text = get_response(self.responses, self.Responses.ask_select_topic)

		dispatcher.utter_message(text=text, buttons=buttons)
		return []


class ActionAskLevel(Action):
	class Responses(ResponseEnum):
		confirm_and_show_change_level = auto()
		ask_select_level = auto()
		level_option_beginner = auto()
		level_option_advanced = auto()
		level_option_expert = auto()

	responses: Dict[str, str]

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

	def name(self):
		return 'action_ask_level'

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		buttons = [
			{'title': get_response(self.responses, self.Responses.level_option_beginner), 'payload': '/inform{"level":"Anfänger"}'},
			{'title': get_response(self.responses, self.Responses.level_option_advanced), 'payload': '/inform{"level":"Fortgeschritten"}'},
			{'title': get_response(self.responses, self.Responses.level_option_expert), 'payload': '/inform{"level":"Experte"}'}]

		intent = str(tracker.get_intent_of_latest_message())
		if intent == 'change_level_slot':
			text = get_response(self.responses, self.Responses.confirm_and_show_change_level)
		else:
			text = get_response(self.responses, self.Responses.ask_select_level)

		dispatcher.utter_message(text=text, buttons=buttons)
		return []


class ActionAskMaxDuration(Action):
	class Responses(ResponseEnum):
		confirm_and_show_change_duration = auto()
		ask_select_duration = auto()
		duration_option_max_10h = auto()
		duration_option_max_50h = auto()
		duration_option_any = auto()

	responses: Dict[str, str]

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

	def name(self):
		return 'action_ask_max_duration'

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		buttons = [
			{'title': get_response(self.responses, self.Responses.duration_option_max_10h), 'payload': '/inform{"max_duration":"10"}'},
			{'title': get_response(self.responses, self.Responses.duration_option_max_50h), 'payload': '/inform{"max_duration":"50"}'},
			{'title': get_response(self.responses, self.Responses.duration_option_any), 'payload': '/inform{"max_duration":"51"}'}]

		intent = str(tracker.get_intent_of_latest_message())
		if intent == 'change_max_duration_slot':
			text = get_response(self.responses, self.Responses.confirm_and_show_change_duration)
		else:
			text = get_response(self.responses, self.Responses.ask_select_duration)

		dispatcher.utter_message(text=text, buttons=buttons)
		return []


class ActionAskCertificate(Action):
	class Responses(ResponseEnum):
		confirm_and_show_change_certificate = auto()
		ask_select_certificate = auto()
		certificate_option_unqualified = auto()
		certificate_option_qualified = auto()
		certificate_option_any = auto()

	responses: Dict[str, str]

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

	def name(self):
		return 'action_ask_certificate'

	def run(self, dispatcher: CollectingDispatcher,
			tracker: Tracker,
			domain: Dict[Text, Any]) -> List[Dict[Text, Any]]:

		buttons = [
			{'title': get_response(self.responses, self.Responses.certificate_option_unqualified), 'payload': '/inform{"certificate":"Teilnahmebescheinigung"}'},
			{'title': get_response(self.responses, self.Responses.certificate_option_qualified), 'payload': '/inform{"certificate":"Leistungsnachweis"}'},
			{'title': get_response(self.responses, self.Responses.certificate_option_any), 'payload': '/undecided'}]

		intent = str(tracker.get_intent_of_latest_message())
		if intent == 'change_certificate_slot':
			text = get_response(self.responses, self.Responses.confirm_and_show_change_certificate)
		else:
			text = get_response(self.responses, self.Responses.ask_select_certificate)

		dispatcher.utter_message(text=text, buttons=buttons)
		return []


class ValidateRecommenderForm(FormValidationAction):
	class Responses(ResponseEnum):
		unsupported_language_selection = auto()
		"""
		text unsupported_language_selection has 1 parameter:
        * parameter {0}: the (unsupported) language
		"""

	responses: Dict[str, str]

	def __init__(self):
		self.responses = get_response_texts(self.name(), ActionResponsesFiles.actions_recommender)
		assert_responses_exist(self.responses, self.Responses)

	def name(self) -> Text:
		return "validate_recommender_form"

	@staticmethod
	def language_db() -> List[Text]:
		"""Database of supported languages"""
		return ["deutsch", "englisch", "egal"]

	@staticmethod
	def language_no_support_db() -> List[Text]:
		"""Database of not supported languages"""
		return ["spanisch", "französisch", "robotisch", "russisch", "slowakisch", "katalanisch", "tschechisch", "mandarin", "hindi", "niederländisch", "schwedisch", "holländisch"]

	@staticmethod
	def topic_db() -> List[Text]:
		"""Database of topics"""
		return ['ki-einführung', 'ki-vertiefung', 'ki-berufsfelder', 'ki-gesellschaft', 'data science', 'maschinelles lernen', 'egal']

	@staticmethod
	def certificate_db() -> List[Text]:
		"""Database of certificates"""
		return ["teilnahmebescheinigung", "leistungsnachweis", "egal"]

	@staticmethod
	def max_duration_db() -> List[Text]:
		"""Database of durations"""
		return ["0", "10", "50", "51"]

	@staticmethod
	def level_db() -> List[Text]:
		"""Database of levels"""
		return ["anfänger", "fortgeschritten", "experte"]

	def validate_language(
		self,
		slot_value: Any,
		dispatcher: CollectingDispatcher,
		tracker: Tracker,
		domain: DomainDict,
	) -> Dict[Text, Any]:
		"""Validate language"""

		if slot_value:
			if slot_value.lower() in self.language_db():
				return {"language": slot_value.lower()}
			elif slot_value.lower() in self.language_no_support_db():
				lang = str(slot_value).capitalize()
				# test for variable
				dispatcher.utter_message(text=get_response(self.responses, self.Responses.unsupported_language_selection).format(lang))
				return {"language": None}

		dispatcher.utter_message(response="utter_interjection_languages")
		return {"language": None}

	def validate_topic(
		self,
		slot_value: Any,
		dispatcher: CollectingDispatcher,
		tracker: Tracker,
		domain: DomainDict,
	) -> Dict[Text, Any]:
		"""Validate topic"""

		if slot_value and slot_value.lower() in self.topic_db():
			return {"topic": slot_value.lower()}
		else:
			dispatcher.utter_message(response = "utter_unavailable_topic")
			return {"topic": None}

	def validate_certificate(
		self,
		slot_value: Any,
		dispatcher: CollectingDispatcher,
		tracker: Tracker,
		domain: DomainDict,
	) -> Dict[Text, Any]:
		"""Validate certificate"""

		if slot_value and slot_value.lower() in self.certificate_db():
			return {"certificate": slot_value.lower()}
		else:
			return {"certificate": None}

	def validate_max_duration(
		self,
		slot_value: Any,
		dispatcher: CollectingDispatcher,
		tracker: Tracker,
		domain: DomainDict,
	) -> Dict[Text, Any]:
		"""Validate max_duration"""

		if slot_value and slot_value.lower() in self.max_duration_db():
			return {"max_duration": slot_value.lower()}
		else:
			return {"max_duration": None}

	def validate_level(
		self,
		slot_value: Any,
		dispatcher: CollectingDispatcher,
		tracker: Tracker,
		domain: DomainDict,
	) -> Dict[Text, Any]:
		"""Validate level"""

		if slot_value and slot_value.lower() in self.level_db():
			return {"level": slot_value.lower()}
		else:
			return {"level": None}
