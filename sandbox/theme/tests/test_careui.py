import pytest
from django import forms

from sandbox.applications.models import Application
from sandbox.applications.models import ApplicationState
from sandbox.theme.templatetags import careui
from sandbox.workflow.registry import WORKFLOWS

LONG_CHOICES = [(str(index), f"Option {index}") for index in range(10)]


class SampleForm(forms.Form):
    email = forms.EmailField(help_text="Where we send credentials.")
    kind = forms.ChoiceField(choices=[("a", "A")])
    notes = forms.CharField(widget=forms.Textarea, required=False)
    agreed = forms.BooleanField()
    upload = forms.FileField(required=False)
    tags = forms.MultipleChoiceField(
        choices=[("a", "Alpha"), ("b", "Beta")],
        widget=forms.CheckboxSelectMultiple,
        required=False,
    )
    many = forms.MultipleChoiceField(
        choices=LONG_CHOICES,
        widget=forms.CheckboxSelectMultiple,
        required=False,
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
        ("upload", "ui-file"),
        # attrs on a choice widget land on each option's input
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
    assert not careui.is_checkbox_group(bound("agreed"))
    assert careui.is_select(bound("kind"))
    assert not careui.is_select(bound("notes"))


# Choice pickers


def test_a_short_choice_set_is_shown_in_full():
    """Opening a two-item list costs more than reading it."""
    field = bound("tags")

    assert careui.is_checkbox_group(field)
    assert careui.ui_field(field)["collapse"] is False


def test_a_long_choice_set_collapses():
    context = careui.ui_field(bound("many"))

    assert context["collapse"] is True


def test_the_closed_summary_names_what_is_chosen():
    context = careui.ui_field(bound("tags", data={"tags": ["a", "b"]}))

    assert context["choice_summary"] == "Alpha, Beta"


def test_the_closed_summary_counts_the_rest_once_it_is_long():
    field = bound("many", data={"many": ["0", "1", "2", "3", "4"]})

    assert careui.ui_field(field)["choice_summary"] == (
        "Option 0, Option 1, Option 2 and 2 more"
    )


def test_the_closed_summary_says_so_when_nothing_is_chosen():
    assert careui.ui_field(bound("tags"))["choice_summary"] == "Nothing selected"


def test_an_unbound_summary_reads_the_initial_values():
    """Resuming a saved draft renders from initial, not from POST data, and the
    values there are the choice values rather than strings."""
    field = SampleForm(initial={"tags": ["b"]})["tags"]

    assert careui.ui_field(field)["choice_summary"] == "Beta"


def test_non_field_errors_are_exposed_to_templates():
    form = SampleForm(data={})
    form.add_error(None, "Something went wrong.")

    assert "Something went wrong." in careui.ui_non_field_errors(form)


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("DRAFT", "neutral"),
        ("SUBMITTED", "primary"),
        ("PROVISIONED", "success"),
        ("APPROVED", "success"),
        ("SENT_BACK", "warning"),
        ("PROVISIONING_FAILED", "destructive"),
        ("REJECTED", "destructive"),
    ],
)
def test_a_state_wears_the_variant_its_meaning_deserves(state, expected):
    assert careui.state_variant(state) == expected


def test_every_reachable_state_has_a_variant():
    """Otherwise a state added to a workflow renders neutral and nobody notices
    until PROVISIONING_FAILED looks like DRAFT on a screen."""
    for key, workflow in WORKFLOWS.items():
        reachable = {workflow.initial_state}
        reachable |= {from_state for from_state, _ in workflow.transitions}
        reachable |= {spec.to_state for spec in workflow.transitions.values()}
        unmapped = sorted(reachable - set(careui.STATE_VARIANTS))
        assert not unmapped, f"{key} has unmapped states: {unmapped}"


def test_an_unknown_state_falls_back_rather_than_raising():
    assert careui.state_variant("SOMETHING_NEW") == "neutral"


def test_every_reachable_state_has_a_label():
    """The variant test's twin. Without it a state reachable by one workflow but
    absent from `ApplicationState` renders as UNDER_REVIEW beside "Provisioned",
    which is how this was found."""
    labelled = set(ApplicationState.values) | set(careui.EXIT_STATE_LABELS)
    for key, workflow in WORKFLOWS.items():
        reachable = {workflow.initial_state}
        reachable |= {from_state for from_state, _ in workflow.transitions}
        reachable |= {spec.to_state for spec in workflow.transitions.values()}
        unlabelled = sorted(reachable - labelled)
        assert not unlabelled, f"{key} has unlabelled states: {unlabelled}"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("UNDER_REVIEW", "Under review"),
        ("SENT_BACK", "Sent back"),
    ],
)
def test_a_state_badge_reads_as_words(state, expected):
    assert careui.state_label(Application(state=state)) == expected
