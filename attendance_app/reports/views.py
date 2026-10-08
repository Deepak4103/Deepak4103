import datetime

from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from academics.models import SchoolClass
from accounts.decorators import admin_required
from attendance.services import today

from . import export
from .builders import BY_SLUG, REPORTS
from .forms import ReportFilterForm


@admin_required
def report_index(request):
    return render(request, "reports/index.html", {"reports": REPORTS})


@admin_required
def report_view(request, slug):
    rdef = BY_SLUG.get(slug)
    if rdef is None:
        from django.http import Http404
        raise Http404
    fmt = request.GET.get("export")
    params = {k: v for k, v in request.GET.items() if k != "export"}
    if not params:                                    # first visit: sensible defaults
        params = {}
        if "date" in rdef.fields:
            params["date"] = today().isoformat()
        if rdef.needs_class:
            first = SchoolClass.objects.first()
            if first:
                params["school_class"] = str(first.pk)
    form = ReportFilterForm(params, fields=rdef.fields, needs_class=rdef.needs_class)   # always bound: no filters = all
    report = None
    if form.is_bound and form.is_valid():
        report = rdef.builder(form.filters())
        if fmt in ("xlsx", "pdf"):
            name = f"{slug}_{datetime.date.today():%Y%m%d}.{fmt}"
            if fmt == "xlsx":
                resp = HttpResponse(export.to_xlsx(report),
                                    content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            else:
                resp = HttpResponse(export.to_pdf(report), content_type="application/pdf")
            resp["Content-Disposition"] = f'attachment; filename="{name}"'
            return resp
    from urllib.parse import urlencode
    return render(request, "reports/report.html", {
        "rdef": rdef, "form": form, "report": report, "query": urlencode({k: v for k, v in params.items() if v}),
        "rows": list(zip(report.rows, [report.flag(i) for i in range(len(report.rows))])) if report else []})
