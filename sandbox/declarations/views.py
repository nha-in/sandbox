"""The only way a declaration document is ever reached.

The bucket is private and has no public URLs; this view resolves an
`external_id` inside the caller's organisation and redirects to a short-lived
presigned GET. Wrong organisation 404s — a 403 would confirm the file exists.
"""

from __future__ import annotations

from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View

from sandbox.declarations.selectors import document_detail
from sandbox.declarations.services import download_url
from sandbox.organisations.mixins import OrganisationMixin


class DocumentDownloadView(LoginRequiredMixin, OrganisationMixin, View):
    def get(self, request, external_id):
        document = document_detail(self.organisation, external_id)
        return redirect(download_url(document))


document_download_view = DocumentDownloadView.as_view()
