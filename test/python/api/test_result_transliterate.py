import json
import xml.etree.ElementTree as ET

import pytest

from nominatim_api.v1.format import dispatch as v1_format
import nominatim_api as napi

FORMATS = ['json', 'jsonv2', 'geojson', 'geocodejson', 'xml']


@pytest.mark.parametrize('fmt', FORMATS)
def test_transliterated_name_in_format(fmt):
    """Test that transliterated_name is included in the formatted output."""
    result = napi.DetailedResult(
        source_table=napi.SourceTable.PLACEX,
        category=('amenity', 'school'),
        centroid=napi.Point(40.7128, -74.0060),
        place_id=12345,
        locale_name="Test School",
        display_name="Test School, New York",
        transliterated_name="Test Transliteration",
        rank_search=30,
        importance=0.5,
        country_code="us"
    )

    raw = v1_format.format_result([result], fmt, {})

    if fmt == 'xml':
        root = ET.fromstring(raw)
        assert root.find('transliterated_name').text == "Test Transliteration"
    else:
        output = json.loads(raw)
        if fmt in ['geojson', 'geocodejson']:
            props = output['features'][0]['properties']
        else:
            props = output
        assert props['transliterated_name'] == "Test Transliteration"