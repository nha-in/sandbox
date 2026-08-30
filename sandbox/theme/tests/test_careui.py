import pytest
from django import forms

from sandbox.theme.templatetags import careui


class SampleForm(forms.Form):
    email = forms.EmailField(help_text="Where we send credentials.")
    kind = forms.ChoiceField(choices=[("a", "A")])
    notes = forms.CharField(widget=forms.Textarea, required=False)
    agreed = forms.BooleanField()
    tags = forms.MultipleChoiceField(
        choices=[("a", "A"), ("b", "B")],
        widget=forms.CheckboxSelectMultiple,
    )
    # No widget named: Django's default for this field is `SelectMultiple`, so
    # this is what anyone gets who adds a multi-choice field without thinking
    # about it.
    regions = forms.MultipleChoiceField(choices=[("a", "A"), ("b", "B")])


def bound(field_name, data=None):
    return SampleForm(data=data)[field_name]


@pytest.mark.parametrize(
    ("field_name", "expected"),
    [
        ("email", "ui-input"),
        ("kind", "ui-select"),
        ("notes", "ui-textarea"),
        ("agreed", "ui-checkbox"),
        ("tags", "ui-checkbox"),
        ("regions", "ui-multiselect"),
    ],
)
def test_each_widget_gets_its_house_control_class(field_name, expected):
    assert expected in careui.ui_widget(bound(field_name))


@pytest.mark.parametrize("field_name", ["tags", "regions"])
def test_a_multi_choice_control_is_never_styled_as_a_dropdown(field_name):
    """`ui-select` is a dropdown's styling — fixed height, chevron,
    appearance-none. On a checkbox group it is meaningless; on a list box it
    collapsed the options into two scrolling rows behind an arrow that opened
    nothing. `SelectMultiple` subclasses `Select`, which is how it got there.
    """
    field = bound(field_name)

    assert "ui-select" not in careui.ui_widget(field)
    assert not careui.is_select(field), "only a dropdown gets the chevron wrapper"


def test_help_text_is_wired_for_screen_readers():
    field = bound("email")

    careui.ui_widget(field)

    assert field.field.widget.attrs["aria-describedby"] == f"{field.auto_id}_helptext"


def test_invalid_fields_are_marked_for_screen_readers():
    field = bound("email", data={"kind": "a", "agreed": "on"})

    careui.ui_widget(field)

    assert field.field.widget.attrs["aria-invalid"] == "true"


def test_ui_field_context_falls_back_to_the_form_declaration():
    context = careui.ui_field(bound("email"))

    assert context["label"] == "Email"
    assert context["help_text"] == "Where we send credentials."
    assert context["is_optional"] is False


def test_ui_field_overrides_win_and_placeholder_reaches_the_widget():
    field = bound("notes")

    context = careui.ui_field(field, label="Anything else?", placeholder="Optional")

    assert context["label"] == "Anything else?"
    assert context["is_optional"] is True
    assert field.field.widget.attrs["placeholder"] == "Optional"


def test_widget_type_filters():
    assert careui.is_checkbox(bound("agreed"))
    assert not careui.is_checkbox(bound("email"))
    assert careui.is_checkbox_group(bound("tags"))
    assert not careui.is_checkbox_group(bound("regions"))
    assert careui.is_select(bound("kind"))
    assert not careui.is_select(bound("notes"))


def test_non_field_errors_are_exposed_to_templates():
    form = SampleForm(data={})
    form.add_error(None, "Something went wrong.")

    assert "Something went wrong." in careui.ui_non_field_errors(form)
