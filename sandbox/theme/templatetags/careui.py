"""Template helpers for rendering forms in the careui idiom.

Django widgets carry their own attrs, and allauth builds a dozen forms we do not
own. Rather than subclass every one of them, these helpers stamp the right
classes onto a bound field at render time, so `{% ui_field form.email %}` looks
the same whoever built the form.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from typing import Any

from django import forms
from django import template
from django.utils.translation import gettext_lazy as _

if TYPE_CHECKING:
    from django.forms import BoundField

register = template.Library()

# Widget class → the careui control class it should render as.
#
# Order matters: `CheckboxSelectMultiple` subclasses `RadioSelect`, so it has to
# be matched first.
_CONTROL_CLASSES: list[tuple[type, str]] = [
    (forms.CheckboxInput, "ui-checkbox"),
    # Attrs on a choice widget land on each option's <input>, so the boxes in a
    # group are styled the same as a lone one.
    (forms.CheckboxSelectMultiple, "ui-checkbox"),
    (forms.RadioSelect, "ui-radio"),
    (forms.Textarea, "ui-textarea"),
    (forms.SelectMultiple, "ui-multiselect"),
    (forms.Select, "ui-select"),
    # Covers ClearableFileInput and A7's multi-upload widget, both subclasses.
    (forms.FileInput, "ui-file"),
]
_DEFAULT_CONTROL_CLASS = "ui-input"

# Widgets that render as a dropdown and therefore need the chevron wrapper.
# `SelectMultiple` subclasses `Select`, so it has to be excluded by name: it is
# a list box that never opens, and the arrow plus `ui-select`'s fixed height
# crushed it into two scrolling rows.
_SELECT_WIDGETS = (forms.Select,)
_LIST_BOX_WIDGETS = (forms.SelectMultiple,)

#: Above this many options a choice group collapses behind a disclosure. Short
#: lists are quicker to read open than to open; long ones bury the rest of the
#: form. Two of the enrolment sets have sixteen and ten.
PICKER_THRESHOLD = 6

#: How many chosen labels the closed summary names before it counts the rest.
_SUMMARY_NAMED = 3

#: Handed to the template so `project.js` can rebuild the same sentence as boxes
#: are ticked. One definition, or the text changes the moment JavaScript loads.
PICKER_EMPTY = _("Nothing selected")
PICKER_MORE = _("and {count} more")


def _control_class(widget: forms.Widget) -> str:
    for widget_type, css_class in _CONTROL_CLASSES:
        if isinstance(widget, widget_type):
            return css_class
    return _DEFAULT_CONTROL_CLASS


def _style(field: BoundField, extra_class: str = "") -> BoundField:
    """Merge careui classes and validation state into the widget's attrs."""
    widget = field.field.widget
    attrs = widget.attrs
    classes = [
        _control_class(widget),
        attrs.get("class", ""),
        extra_class,
    ]
    merged = " ".join(part for part in classes if part).strip()
    if merged:
        attrs["class"] = merged
    if field.errors:
        attrs["aria-invalid"] = "true"
    if field.help_text and "aria-describedby" not in attrs:
        attrs["aria-describedby"] = f"{field.auto_id}_helptext"
    return field


@register.simple_tag
def ui_widget(field: BoundField, extra_class: str = "") -> str:
    """Render just the control, already carrying its careui classes."""
    return _style(field, extra_class).as_widget()


@register.filter
def is_checkbox(field: BoundField) -> bool:
    return isinstance(field.field.widget, forms.CheckboxInput)


@register.filter
def is_checkbox_group(field: BoundField) -> bool:
    return isinstance(field.field.widget, forms.CheckboxSelectMultiple)


@register.filter
def is_select(field: BoundField) -> bool:
    widget = field.field.widget
    return isinstance(widget, _SELECT_WIDGETS) and not isinstance(
        widget,
        _LIST_BOX_WIDGETS,
    )


def _choices(field: BoundField) -> list[tuple[Any, Any]]:
    """Only choice fields have them, and `Field` does not declare the attribute."""
    return list(getattr(field.field, "choices", None) or [])


def _chosen_labels(field: BoundField) -> list[str]:
    """The labels behind the chosen values, in the order the field declares them.

    Both sides are compared as strings: bound data arrives from the POST as
    text, while an unbound initial may hold the choice values themselves.
    """
    selected = {str(value) for value in (field.value() or [])}
    return [str(label) for value, label in _choices(field) if str(value) in selected]


def _choice_summary(field: BoundField) -> str:
    """What the closed picker says. `project.js` recomputes this as boxes are
    ticked; the server-rendered text is what a reader with no JavaScript sees,
    so it has to be right on its own."""
    labels = _chosen_labels(field)
    if not labels:
        return str(PICKER_EMPTY)
    if len(labels) <= _SUMMARY_NAMED:
        return ", ".join(labels)
    named = ", ".join(labels[:_SUMMARY_NAMED])
    more = str(PICKER_MORE).format(count=len(labels) - _SUMMARY_NAMED)
    return f"{named} {more}"


@register.inclusion_tag("components/form_field.html")
def ui_field(
    field: BoundField,
    label: str = "",
    placeholder: str = "",
    help_text: str = "",
    *,
    optional: bool | None = None,
) -> dict:
    """Render a full label + control + help + errors block.

    `label`, `placeholder` and `help_text` override whatever the form declared,
    which is how the allauth screens pick up the mockup's copy without us
    reaching into allauth's form classes.

    `optional` overrides the marker for the case the per-field flag cannot
    express: two fields that are each `required=False` because the rule is
    "one of these two", where marking both optional tells the user nothing is
    needed and then refuses the form.
    """
    if placeholder:
        field.field.widget.attrs["placeholder"] = placeholder
    group = is_checkbox_group(field)
    return {
        "field": _style(field),
        "label": label or field.label,
        "help_text": help_text or field.help_text,
        # The mockups mark nothing as required — almost every field is. Flag the
        # exceptions instead, which is both closer to the design and the clearer
        # convention.
        "is_optional": not field.field.required if optional is None else optional,
        "collapse": group and len(_choices(field)) > PICKER_THRESHOLD,
        "choice_summary": _choice_summary(field) if group else "",
        "picker_empty": PICKER_EMPTY,
        "picker_more": PICKER_MORE,
    }


@register.simple_tag
def ui_non_field_errors(form) -> dict:
    return form.non_field_errors()
