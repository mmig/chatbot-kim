from enum import Enum
from typing import Dict, Optional, Union

import yaml
import os


class RecommenderConfigEnum(Enum):
	""" Enum known fields in recommender configuration """
	URL = 'url'
	TOKEN = 'token'


def load_config(file_name: str, relative_dir_path: Optional[str] = None) -> Dict[str, Dict[str, any]]:
	"""
	load YAML with dictionary-like structure at its root

	:param file_name: the file name for the YAML file (including its file extension)
	:param relative_dir_path: OPTIONAL the subdirectory, relative the root directory
										(if omitted, file is assumed to be in the rasa-project's root directory)
	:return: the load YAML data
	"""
	target_dir = os.path.join('..', relative_dir_path) if relative_dir_path else '..'
	response_texts_path = os.path.join(os.path.dirname(__file__), target_dir, file_name)
	with open(response_texts_path, 'r', encoding='utf-8') as file:
		return yaml.safe_load(file)


def load_recommender_config() -> Dict[str, str]:
	"""
	HELPER load the configuration for the (DFKI) recommender API (entry for "recommender_api" in file kic_recommender.yml)
	:return: the configuration for the base URL ("url") and access token ("token") for course-recommender endpoint
	"""
	recommender_config: Dict[str, Dict[str, str]] = load_config('kic_recommender.yml')

	return recommender_config['recommender_api']


_recommender_config: Optional[Dict[str, Dict[str, str]]] = None
""" INTERNAL cache for recommender configuration data """


def get_recommender_config(field: Optional[Union[str, RecommenderConfigEnum]] = None, force_reloading: bool = False) -> Union[Dict[str, str], str]:
	"""
	HELPER get the configuration for the (DFKI) recommender API

	:param field: OPTIONAL if specified: get specific configuration value for `field` instead of configuration dictionary
	:param force_reloading: OPTIONAL if `True`, forces reloading the configuration data from file
	:return: the configuration for the base URL ("url") and access token ("token") for course-recommender endpoint
	"""
	global _recommender_config
	if not _recommender_config or force_reloading:
		_recommender_config = load_recommender_config()
	if field:
		if isinstance(field, RecommenderConfigEnum):
			return _recommender_config[field.value]
		return _recommender_config[field]
	return _recommender_config
