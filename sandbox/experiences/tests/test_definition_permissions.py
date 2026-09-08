"""§4.8: `required_permissions`, and the guard that keeps it safe.

Declaring the mapping replaces it rather than merging, so that a form cannot
inherit half an audience it did not mean to. The cost is that a definition can
drop its acting permission, and `validate()` is where that is caught.
"""

from __future__ import annotations

import pytest
from django import forms
from django.core.exceptions import ImproperlyConfigured

from sandbox.experiences import permission_keys
from sandbox.experiences.definitions import COMMON_PERMISSIONS
from sandbox.experiences.definitions import ApplicationAction
from sandbox.experiences.definitions import ApplicationDefinition
from sandbox.experiences.definitions import ApplicationFormDefinition
from sandbox.experiences.definitions import RoleDefinition
from sandbox.experiences.definitions import StatusDefinition
from sandbox.experiences.registry import registry

APPLICATION_TYPE = "abdm_milestone_exit"


class BareForm(forms.Form):
    field = forms.CharField()


def definition_with(*, form_classes=(), action_classes=()):
    # Bound outside the class body: a class body is not a closure, so
    # `actions = actions` there would not see the parameter.
    declared_forms, declared_actions = form_classes, action_classes

    class Throwaway(ApplicationDefinition):
        key = "throwaway"
        name = "Throwaway"
        description = "Only ever validated."
        statuses = (StatusDefinition("draft", "Draft", "", "muted"),)
        permissions = COMMON_PERMISSIONS
        roles = (
            RoleDefinition(
                "applicant_owner",
                "Owner",
                "",
                "organisation",
                frozenset({permission_keys.VIEW_APPLICATION}),
            ),
        )
        forms = declared_forms
        actions = declared_actions

    return Throwaway


def test_view_falls_back_to_the_acting_permission():
    class ReviewerOnly(ApplicationFormDefinition):
        key = "reviewer_only"
        name = "Reviewer only"
        description = ""
        form_class = BareForm
        required_permissions = {"edit": permission_keys.APPROVE_APPLICATION}

    assert ReviewerOnly.permission_for("edit") == permission_keys.APPROVE_APPLICATION
    assert ReviewerOnly.permission_for("view") == permission_keys.APPROVE_APPLICATION


def test_an_undeclared_mapping_is_inherited_whole():
    class Ordinary(ApplicationFormDefinition):
        key = "ordinary"
        name = "Ordinary"
        description = ""
        form_class = BareForm

    assert Ordinary.permission_for("edit") == permission_keys.EDIT_FORMS
    assert Ordinary.permission_for("view") == permission_keys.VIEW_APPLICATION


def test_a_form_that_drops_its_acting_permission_is_refused():
    class ViewOnly(ApplicationFormDefinition):
        key = "view_only"
        name = "View only"
        description = ""
        form_class = BareForm
        required_permissions = {"view": permission_keys.VIEW_APPLICATION}

    with pytest.raises(ImproperlyConfigured, match="no 'edit' permission"):
        definition_with(form_classes=(ViewOnly,)).validate()


def test_an_action_that_drops_its_acting_permission_is_refused():
    class Nameless(ApplicationAction):
        key = "nameless"
        name = "Nameless"
        description = ""
        required_permissions = {"view": permission_keys.VIEW_APPLICATION}

    with pytest.raises(ImproperlyConfigured, match="no 'perform' permission"):
        definition_with(action_classes=(Nameless,)).validate()


def test_an_undeclared_permission_key_is_refused():
    class Invented(ApplicationAction):
        key = "invented"
        name = "Invented"
        description = ""
        required_permissions = {"perform": "application.invented"}

    with pytest.raises(ImproperlyConfigured, match="unknown permissions"):
        definition_with(action_classes=(Invented,)).validate()


def test_every_capability_is_checked_not_only_the_acting_one():
    class WidelyVisible(ApplicationAction):
        key = "widely_visible"
        name = "Widely visible"
        description = ""
        required_permissions = {
            "perform": permission_keys.APPROVE_APPLICATION,
            "view": "application.invented",
        }

    with pytest.raises(ImproperlyConfigured, match="unknown permissions"):
        definition_with(action_classes=(WidelyVisible,)).validate()


def test_the_registered_definition_validates():
    registry.get(APPLICATION_TYPE).validate()
