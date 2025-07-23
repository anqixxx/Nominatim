# Proof of concept of transliteration using Nominatim as a library
from .localization import Locales
import nominatim_api as napi
from unidecode import unidecode
import yaml
import opencc
from cantoroman import Cantonese # only works from cantonese (written zh-Hant script) to latin
from typing import Optional, Tuple, Sequence, TypeVar, Type, List, cast, Callable, Mapping
from typing import Mapping, List, Optional
from .config import Configuration
import os
from abc import ABC, abstractmethod
import re
import asyncio  


# Planning on changing name later, this is just for now
class Transliterator(Locales, ABC):
    """
    Abstract base class for transliterators using Locales for language info.
    """

    def __init__(self, langs: Optional[list[str]] = None):
        super().__init__(langs)

        # yaml information for now
        self.country_data = load_country_info()
        self.lang_data = load_lang_info()
    

    @staticmethod
    def get_locales(results):
        """ Given a list of results, prints out all locales
            associated with the results
        """
        locale_set = set()
        for result in results:
            if result.names:
                locale_set.update(result.names.keys())
            if result.address_rows:
                for row in result.address_rows:
                    if row.names:
                        locale_set.update(row.names.keys())
        return sorted(locale_set)


    def _get_languages(self, result):
        """ Given a result, returns the languages associated with the region

            Special handling is needed for Macau and Hong Kong (not in yaml)
        """
        print("RESULT")
        print(result)
        print(type(result))
        if not self.country_data:
            self.country_data = load_country_info()
        print(result)
        country = self.country_data.get(result.country_code.lower()) 
        if country and 'languages' in country:
            return [lang.strip() for lang in country['languages'].split(',')]
        return []


    def _latin(self, language_code) -> bool:
        """ Using languages.yaml, returns if the 
            given language is latin based or not.

            If the code does not exist in the yaml file, it 
            will return false. This works as, due to normalization,
            we assume that the "prime" version of the code is also in 
            the user languages, so it will eventually execute

            Will only work on two-letter ISO 639 language codes
            with the exception of yue, which is also included
        """
        if not self.lang_data:
            self.lang_data = load_lang_info()

        language = self.lang_data.get(language_code)
        if language:
            return language['written'] == 'lat'
        return False


    @staticmethod
    def _normalize_lang(lang):
        """ Mock idea for language mapping dictionary

            Hoping to standardize certain names, i.e.
            zh and zh-cn will always map to zh-Hans
            zh-tw will always map to zh-Hant

            In the case of ambiguity, the largest number of 
            languages will be added

            For all other languages, follow Nominatim precedent
            and just concatenate after the '-'

            Code assumes all language codes are in two letter format 
            https://en.wikipedia.org/wiki/List_of_ISO_639_language_codes 
            with the exception of yue 
        """
        # Potentially make this a global variable (or object field) to reduce compute
        # For zh-Latn-pinyin and zh-Latn, I did not include this as it is not really a spoken language
        # For now, no dialect support
        lang_dict = {
            "zh": ["zh-Hans", "zh-Hant", "yue"], # zh covers zh-Hans, zh-Hant, yue
            "zh-cn": ["zh-Hans"], # only Simplfied 
            "zh-tw": ["zh-Hant"], # only Traditional Mandarin
            "zh-hans": ["zh-Hans"],
            "zh-hant": ["zh-Hant", "yue"], # Traditional implies both canto & mando
            "zh-Hans-CN": ["zh-Hans"], # only Simplfied 
            "zh-cmn": ["zh-Hans"], # only Simplified, cmn means Mandarin
            "zh-cmn-Hans": ["zh-Hans"],  # only Simplified, cmn means Mandarin
            "zh-cmn-Hant": ["zh-Hant"]  # only Traditional, cmn means Mandarin
        }

        if lang in lang_dict:
        #  Ordering nessecary due to zh edge case (no '-')
            return lang_dict[lang]
        elif '-' not in lang:
            return [lang]
        return [lang.split('-')[0]]


    @classmethod
    def from_accept_languages(cls, langstr: str) -> 'Transliterator':
        """ Create a localization object from a language list in the
            format of HTTP accept-languages header.

            The functions tries to be forgiving of format errors by first splitting
            the string into comma-separated parts and then parsing each
            description separately. Badly formatted parts are then ignored.

            Using the additional normalization transliteration constraints,
            then returns the larguage in its normalized form, as well as the regional 
            dialect, if applicable.

            The regional dialect always takes precedence

            Languages are returned in lowercase form
        """
        # split string into languages
        candidates = []
        for desc in langstr.split(','):
            m = re.fullmatch(r'\s*([a-z_-]+)(?:;\s*q\s*=\s*([01](?:\.\d+)?))?\s*',
                                desc, flags=re.I)
            if m:
                candidates.append((m[1], float(m[2] or 1.0)))

        # sort the results by the weight of each language (preserving order).
        candidates.sort(reverse=True, key=lambda e: e[1])

        # if a language has a region variant, ignore it
        # we want base transliteration language only
        languages = []
        for lid, _ in candidates:
            lid = lid

            if lid not in languages:
                languages.append(lid)

            normalized = cls._normalize_lang(lid)
            for norm_lang in normalized:
                if norm_lang not in languages:
                    languages.append(norm_lang)
        return cls(languages)


    def display_name_with_locale(self, names: Optional[Mapping[str, str]]) -> Tuple[str, str]:
        """ Return the best matching name from a dictionary of names
            containing different name variants, as well as an identifier 
            with regards to what language used

            If 'names' is null or empty, an empty tuple is returned. If no
            appropriate localization is found, the first name is returned with
            the 'default' marker, where afterwards iso is used.
        """
        if not names:
            return ['', '']
        
        if len(names) > 1:
            for tag in self.name_tags:
                if tag in names:
                    return [names[tag], tag.split(':', 1)[1]]

        # Nothing? Return any of the other names as a default.
        return [next(iter(names.values())), "default"] # want to see what this will return


    def display_name(self, names: Optional[Mapping[str, str]]) -> str:
        return self.display_name_with_locale(names)[0]


def include_constructor(loader, node):
    # Temporary file to get rid of !include error for yaml

    file_path = loader.construct_scalar(node)
    full_path = os.path.join(os.path.dirname(loader.name), file_path)
    with open(full_path, 'r') as f:
        return yaml.safe_load(f)


def load_country_info(yaml_path=None):
    """ Loads country_settings
        Yaml files from Nominatim blob/master/settings/country_settings.yaml 
    """
    yaml.SafeLoader.add_constructor('!include', include_constructor)

    if yaml_path is None:
        current_dir = os.path.dirname(__file__)
        yaml_path = os.path.join(current_dir, "../../settings", "country_settings.yaml")
    with open(yaml_path, 'r') as file:
        yaml.SafeLoader.name = file.name  # Pass the file name to the loader
        return yaml.safe_load(file)
    

def load_lang_info(yaml_path=None):
    """ Loads language information on writing system

    Will only work on two-letter ISO 639 language codes
    with the exception of yue, which is also included
    """
    if yaml_path is None:
        current_dir = os.path.dirname(__file__)
        yaml_path = os.path.join(current_dir, "../../settings", "languages.yaml")

    with open(yaml_path, 'r') as file:
        return yaml.safe_load(file)


async def search(query):
    """ Nominatim Search Query
    """
    # async with napi.NominatimAPIAsync() as api:
    #     return await api.search(query, address_details=True)
        # return await api.search(query)
    pass


# header = "zh-CN,zh;q=0.8,en-US;q=0.5"
header = "fr,en-US;q=0.5"
t = Transliterator.from_accept_languages(header)
print(t.languages)