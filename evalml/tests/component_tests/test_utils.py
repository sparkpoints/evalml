from importlib import import_module
from unittest.mock import patch

import pytest

from evalml.pipelines.components import all_components, handle_component
from evalml.tests.conftest import has_core_deps


@pytest.mark.skipif(has_core_deps(), reason="Skipping test because xgboost/catboost not installed")
def test_all_components():
    assert len(all_components()) == 12


@pytest.mark.skipif(not has_core_deps(), reason="Skipping test because xgboost/catboost are installed")
def test_all_components_core_dependencies():
    assert len(all_components()) == 9


def make_mock_import_module(libs_to_blacklist):
    def _import_module(library):
        if library in libs_to_blacklist:
            raise ImportError("Cannot import {}; blacklisted by mock muahahaha".format(library))
        return import_module(library)
    return _import_module


@patch('importlib.import_module', make_mock_import_module({'xgboost', 'catboost'}))
def test_all_components_core_dependencies_mock():
    assert len(all_components()) == 9


def test_handle_component_names():
    for name, cls in all_components().items():
        assert isinstance(handle_component(cls()), cls)
        assert isinstance(handle_component(name), cls)

    invalid_name = 'This Component Does Not Exist'
    with pytest.raises(KeyError):
        handle_component(invalid_name)

    class NonComponent:
        pass
    with pytest.raises(ValueError):
        handle_component(NonComponent())
