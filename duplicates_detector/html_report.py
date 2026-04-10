"""Self-contained HTML report generation for duplicate scan results."""

from __future__ import annotations

import base64
import html
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, TextIO

from duplicates_detector.config import Mode
from duplicates_detector.filters import format_size_human
from duplicates_detector.keeper import pick_keep, pick_keep_from_group
from duplicates_detector.reporter import (
    _format_breakdown_verbose,
    _format_duration,
    _format_resolution,
)
from duplicates_detector.thumbnails import (
    collect_group_metadata as _collect_group_metadata,
    collect_pair_metadata as _collect_pair_metadata,
    generate_thumbnails_batch,
)

if TYPE_CHECKING:
    from duplicates_detector.advisor import DeletionSummary
    from duplicates_detector.analytics import AnalyticsResult
    from duplicates_detector.grouper import DuplicateGroup
    from duplicates_detector.metadata import VideoMetadata
    from duplicates_detector.pipeline import PipelineController
    from duplicates_detector.scorer import ScoredPair
    from duplicates_detector.summary import PipelineStats

_THUMB_MAX_SIZE = (120, 120)


def _escape(text: object) -> str:
    """Escape user-supplied content for safe HTML embedding."""
    return html.escape(str(text), quote=True)


def _score_css_class(score: float) -> str:
    """Return CSS class name matching reporter.py score_color() thresholds."""
    if score >= 80:
        return "score-high"
    if score >= 60:
        return "score-med"
    return "score-low"


# ---------------------------------------------------------------------------
# Thumbnail generation (delegates to thumbnails.py)
# ---------------------------------------------------------------------------


def _thumbnail_placeholder(extension: str) -> str:
    """Return an inline SVG data URI placeholder showing the file extension."""
    ext = _escape(extension.upper().lstrip("."))
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80">'
        '<rect width="80" height="80" rx="4" fill="#ddd"/>'
        f'<text x="40" y="44" text-anchor="middle" font-family="sans-serif" '
        f'font-size="14" fill="#888">{ext}</text>'
        "</svg>"
    )
    b64 = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{b64}"


def _generate_all_thumbnails(
    metadata_list: list[VideoMetadata],
    *,
    mode: str = Mode.VIDEO,
    quiet: bool = False,
    controller: PipelineController | None = None,
) -> dict[Path, str]:
    """Generate thumbnails for unique files, returning path → data URI mapping.

    Delegates to :func:`thumbnails.generate_thumbnails_batch` with
    the HTML-specific default size, filtering out ``None`` failures
    (HTML uses placeholder SVGs instead).
    """
    batch = generate_thumbnails_batch(
        metadata_list,
        mode=mode,
        max_size=_THUMB_MAX_SIZE,
        quiet=quiet,
        controller=controller,
    )
    return {path: uri for path, uri in batch.items() if uri is not None}


def _get_thumbnail(
    meta: VideoMetadata,
    thumbnails: dict[Path, str],
) -> str:
    """Get thumbnail data URI for a file, falling back to placeholder."""
    resolved = meta.path.resolve()
    if resolved in thumbnails:
        return thumbnails[resolved]
    return _thumbnail_placeholder(meta.path.suffix)


# ---------------------------------------------------------------------------
# HTML template pieces
# ---------------------------------------------------------------------------

_CSS = """\
:root {
  --color-high: #e74c3c;
  --color-med: #f39c12;
  --color-low: #27ae60;
  --bg: #fafafa;
  --card-bg: #fff;
  --border: #e0e0e0;
  --text: #333;
  --text-dim: #888;
}
*, *::before, *::after { box-sizing: border-box; }
body {
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  background: var(--bg); color: var(--text); margin: 0; padding: 24px;
  line-height: 1.5;
}
h1 { margin: 0 0 16px; font-size: 1.5rem; }
.dashboard {
  display: flex; flex-wrap: wrap; gap: 12px; margin-bottom: 24px;
}
.card {
  background: var(--card-bg); border: 1px solid var(--border); border-radius: 8px;
  padding: 16px 20px; min-width: 140px; flex: 1;
}
.card .label { font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; letter-spacing: 0.5px; }
.card .value { font-size: 1.4rem; font-weight: 700; margin-top: 4px; }
.table-wrap { overflow-x: auto; margin-bottom: 24px; }
table {
  width: 100%; border-collapse: collapse; background: var(--card-bg);
  border: 1px solid var(--border); border-radius: 8px; overflow: hidden;
  font-size: 0.9rem;
}
th, td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--border); }
th {
  background: #f5f5f5; font-weight: 600; position: sticky; top: 0; z-index: 1;
  white-space: nowrap; user-select: none;
}
th.sortable { cursor: pointer; }
th.sortable::after { content: " \\2195"; color: #ccc; font-size: 0.75em; }
th.sort-asc::after { content: " \\25B2"; color: var(--text); }
th.sort-desc::after { content: " \\25BC"; color: var(--text); }
tr:nth-child(even) { background: #fafafa; }
tr:hover { background: #f0f4ff; }
.thumb { max-width: 120px; max-height: 120px; border-radius: 4px; vertical-align: middle; }
.score-badge {
  display: inline-block; padding: 2px 8px; border-radius: 12px;
  color: #fff; font-weight: 700; font-size: 0.85rem;
}
.score-high { background: var(--color-high); }
.score-med { background: var(--color-med); }
.score-low { background: var(--color-low); }
.keep-tag {
  display: inline-block; padding: 1px 6px; border-radius: 4px;
  background: var(--color-low); color: #fff; font-size: 0.75rem; font-weight: 600;
  margin-left: 4px;
}
.ref-tag {
  display: inline-block; padding: 1px 6px; border-radius: 4px;
  background: #95a5a6; color: #fff; font-size: 0.75rem; font-weight: 600;
  margin-left: 4px;
}
.breakdown { font-size: 0.8rem; color: var(--text-dim); }
.path-cell { max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
details { margin-bottom: 16px; }
summary {
  cursor: pointer; font-weight: 600; font-size: 1.05rem; padding: 8px 12px;
  background: #f5f5f5; border: 1px solid var(--border); border-radius: 8px;
  list-style-position: inside;
}
details[open] > summary { border-radius: 8px 8px 0 0; }
details > .group-content {
  border: 1px solid var(--border); border-top: none; border-radius: 0 0 8px 8px;
  padding: 12px;
}
.dry-run-box {
  background: #fff9e6; border: 1px solid #f0d060; border-radius: 8px;
  padding: 16px 20px; margin-top: 24px;
}
.dry-run-box h2 { margin: 0 0 8px; font-size: 1.1rem; color: #b8860b; }
.no-results { padding: 40px; text-align: center; color: var(--text-dim); font-size: 1.1rem; }
.footer { margin-top: 32px; text-align: center; font-size: 0.8rem; color: var(--text-dim); }
@media print {
  body { padding: 12px; }
  th.sortable::after { content: none; }
  tr:hover { background: inherit; }
  .dashboard { page-break-inside: avoid; }
}
"""

_JS = """\
document.addEventListener("DOMContentLoaded", function() {
  document.querySelectorAll("th.sortable").forEach(function(th) {
    th.addEventListener("click", function() {
      var table = th.closest("table");
      var tbody = table.querySelector("tbody");
      var idx = Array.from(th.parentNode.children).indexOf(th);
      var rows = Array.from(tbody.querySelectorAll("tr"));
      var asc = !th.classList.contains("sort-asc");
      table.querySelectorAll("th").forEach(function(h) {
        h.classList.remove("sort-asc", "sort-desc");
      });
      th.classList.add(asc ? "sort-asc" : "sort-desc");
      rows.sort(function(a, b) {
        var av = a.children[idx].getAttribute("data-sort-value") || a.children[idx].textContent;
        var bv = b.children[idx].getAttribute("data-sort-value") || b.children[idx].textContent;
        var an = parseFloat(av), bn = parseFloat(bv);
        var cmp = (!isNaN(an) && !isNaN(bn)) ? an - bn : av.localeCompare(bv);
        return asc ? cmp : -cmp;
      });
      rows.forEach(function(r) { tbody.appendChild(r); });
    });
  });
});
"""


def _html_head(title: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n"
        "</head>\n<body>\n"
        f"<h1>{_escape(title)}</h1>\n"
    )


def _html_foot() -> str:
    try:
        from duplicates_detector._version import __version__
    except ImportError:
        __version__ = "dev"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return (
        f'<div class="footer">Generated by duplicates-detector v{_escape(__version__)} '
        f"at {_escape(ts)}</div>\n"
        f"<script>{_JS}</script>\n"
        "</body>\n</html>\n"
    )


# ---------------------------------------------------------------------------
# Summary dashboard
# ---------------------------------------------------------------------------


def _html_summary_dashboard(
    stats: PipelineStats | None,
    pair_count: int,
    group_count: int | None = None,
    mode: str = Mode.VIDEO,
) -> str:
    cards: list[str] = []

    def _card(label: str, value: str) -> str:
        return (
            f'<div class="card"><div class="label">{_escape(label)}</div>'
            f'<div class="value">{_escape(value)}</div></div>'
        )

    if stats is not None:
        cards.append(_card("Files scanned", f"{stats.files_scanned:,}"))
    if group_count is not None:
        cards.append(_card("Groups", f"{group_count:,}"))
    else:
        cards.append(_card("Pairs", f"{pair_count:,}"))
    if stats is not None and stats.space_recoverable > 0:
        cards.append(_card("Space recoverable", format_size_human(stats.space_recoverable)))
    cards.append(_card("Mode", mode))

    return '<div class="dashboard">' + "".join(cards) + "</div>\n"


# ---------------------------------------------------------------------------
# Analytics dashboard
# ---------------------------------------------------------------------------


def _load_resource(name: str) -> str:
    """Load a text resource from the ``_resources`` package."""
    from importlib.resources import files

    return files("duplicates_detector._resources").joinpath(name).read_text(encoding="utf-8")


def _html_analytics_dashboard(analytics: AnalyticsResult) -> str:
    """Return an HTML analytics dashboard section with Chart.js visualisations.

    The section is wrapped in a ``<details open>`` element containing four
    charts arranged in a 2x2 CSS grid:

    1. Directory treemap (sized by total_size, coloured by duplicate_density)
    2. Score distribution histogram
    3. File-type doughnut chart (toggle count/size)
    4. Creation timeline (duplicate files by date)
    """
    from duplicates_detector.analytics import analytics_to_dict

    data = analytics_to_dict(analytics)
    data_json = json.dumps(data, separators=(",", ":"))
    # Escape for safe embedding inside a <script> block.
    data_json_escaped = data_json.replace("</", "<\\/")

    parts: list[str] = []

    # Open wrapper
    parts.append('<details open style="margin-bottom:24px">')
    parts.append(
        '<summary style="cursor:pointer;font-weight:600;font-size:1.05rem;'
        "padding:8px 12px;background:#f5f5f5;border:1px solid var(--border);"
        'border-radius:8px;list-style-position:inside">'
        "Analytics Dashboard</summary>\n"
    )
    parts.append(
        '<div style="border:1px solid var(--border);border-top:none;border-radius:0 0 8px 8px;padding:16px">\n'
    )

    # Inline Chart.js and treemap plugin
    parts.append("<script>")
    parts.append(_load_resource("chartjs.min.js"))
    parts.append("</script>\n")
    parts.append("<script>")
    parts.append(_load_resource("chartjs-chart-treemap.min.js"))
    parts.append("</script>\n")

    # Inject analytics data via a JSON script tag (avoids single-quote escaping issues in paths)
    parts.append(f'<script type="application/json" id="analytics-data">{data_json_escaped}</script>\n')

    # 2x2 CSS grid
    parts.append('<div style="display:grid;grid-template-columns:1fr 1fr;gap:16px">\n')

    # ---- 1. Directory treemap ----
    parts.append('<div style="max-height:350px;position:relative">')
    if data["directory_stats"]:
        parts.append('<canvas id="chart-treemap"></canvas>')
    else:
        parts.append(
            '<div style="color:var(--text-dim);padding:40px;text-align:center">No directory data available</div>'
        )
    parts.append("</div>\n")

    # ---- 2. Score distribution histogram ----
    parts.append('<div style="max-height:350px;position:relative">')
    if data["score_distribution"]:
        parts.append('<canvas id="chart-scores"></canvas>')
    else:
        parts.append('<div style="color:var(--text-dim);padding:40px;text-align:center">No score data available</div>')
    parts.append("</div>\n")

    # ---- 3. File-type doughnut ----
    parts.append('<div style="max-height:350px;position:relative">')
    if data["filetype_breakdown"]:
        parts.append(
            '<div style="text-align:right;margin-bottom:4px">'
            '<button id="ft-toggle" style="font-size:0.75rem;cursor:pointer;'
            "padding:2px 8px;border:1px solid var(--border);border-radius:4px;"
            'background:var(--card-bg)">by size</button></div>'
        )
        parts.append('<canvas id="chart-filetypes"></canvas>')
    else:
        parts.append(
            '<div style="color:var(--text-dim);padding:40px;text-align:center">No file-type data available</div>'
        )
    parts.append("</div>\n")

    # ---- 4. Creation timeline ----
    parts.append('<div style="max-height:350px;position:relative">')
    if data["creation_timeline"]:
        parts.append('<canvas id="chart-timeline"></canvas>')
    else:
        parts.append(
            '<div style="color:var(--text-dim);padding:40px;text-align:center">No timeline data available</div>'
        )
    parts.append("</div>\n")

    # Close grid
    parts.append("</div>\n")

    # Chart initialisation script
    parts.append("<script>\n")
    parts.append(_ANALYTICS_JS)
    parts.append("</script>\n")

    # Close wrapper
    parts.append("</div></details>\n")
    return "".join(parts)


_ANALYTICS_JS = """\
(function(){
  var analyticsData=JSON.parse(document.getElementById('analytics-data').textContent);
  function densityColor(d){
    if(d<0.2) return 'rgba(39,174,96,0.8)';
    if(d<0.5) return 'rgba(243,156,18,0.8)';
    return 'rgba(231,76,60,0.8)';
  }
  function fmtBytes(b){
    if(b<1024) return b+' B';
    if(b<1048576) return (b/1024).toFixed(1)+' KB';
    if(b<1073741824) return (b/1048576).toFixed(1)+' MB';
    return (b/1073741824).toFixed(1)+' GB';
  }

  /* 1. Directory treemap */
  var ds=analyticsData.directory_stats;
  if(ds.length && document.getElementById('chart-treemap')){
    new Chart(document.getElementById('chart-treemap'),{
      type:'treemap',
      data:{datasets:[{
        tree:ds,
        key:'total_size',
        labels:{display:true,formatter:function(c){
          var d=c.raw._data;return d?d.path.split('/').pop()||d.path:'';
        }},
        backgroundColor:function(c){return c.raw._data?densityColor(c.raw._data.duplicate_density):'#ccc';}
      }]},
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{
          title:{display:true,text:'Directory Treemap (sized by total size, coloured by duplicate density)'},
          legend:{display:false},
          tooltip:{callbacks:{
            title:function(items){var d=items[0].raw._data;return d?d.path:'';},
            label:function(item){
              var d=item.raw._data;
              if(!d) return '';
              return [
                'Files: '+d.total_files,
                'Duplicates: '+d.duplicate_files,
                'Total size: '+fmtBytes(d.total_size),
                'Recoverable: '+fmtBytes(d.recoverable_size)
              ];
            }
          }}
        }
      }
    });
  }

  /* 2. Score distribution histogram */
  var sd=analyticsData.score_distribution;
  if(sd.length && document.getElementById('chart-scores')){
    new Chart(document.getElementById('chart-scores'),{
      type:'bar',
      data:{
        labels:sd.map(function(b){return b.range;}),
        datasets:[{
          label:'Pairs',
          data:sd.map(function(b){return b.count;}),
          backgroundColor:'rgba(52,152,219,0.7)',
          borderColor:'rgba(52,152,219,1)',
          borderWidth:1
        }]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{title:{display:true,text:'Score Distribution'}},
        scales:{y:{beginAtZero:true,ticks:{precision:0}}}
      }
    });
  }

  /* 3. File-type doughnut */
  var ft=analyticsData.filetype_breakdown;
  if(ft.length && document.getElementById('chart-filetypes')){
    var top8=ft.slice(0,8);
    var rest=ft.slice(8);
    var labels=top8.map(function(e){return e.extension||'(none)';});
    var countData=top8.map(function(e){return e.count;});
    var sizeData=top8.map(function(e){return e.size;});
    if(rest.length){
      labels.push('Other');
      countData.push(rest.reduce(function(a,e){return a+e.count;},0));
      sizeData.push(rest.reduce(function(a,e){return a+e.size;},0));
    }
    var palette=[
      '#3498db','#e74c3c','#2ecc71','#f39c12','#9b59b6',
      '#1abc9c','#e67e22','#34495e','#95a5a6'
    ];
    var ftMode='count';
    var ftChart=new Chart(document.getElementById('chart-filetypes'),{
      type:'doughnut',
      data:{
        labels:labels,
        datasets:[{data:countData,backgroundColor:palette.slice(0,labels.length)}]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{
          title:{display:true,text:'File Types (by count)'},
          tooltip:{callbacks:{label:function(item){
            if(ftMode==='count') return item.label+': '+item.raw;
            return item.label+': '+fmtBytes(item.raw);
          }}}
        }
      }
    });
    var btn=document.getElementById('ft-toggle');
    if(btn){btn.addEventListener('click',function(){
      if(ftMode==='count'){
        ftMode='size';
        ftChart.data.datasets[0].data=sizeData;
        ftChart.options.plugins.title.text='File Types (by size)';
        btn.textContent='by count';
      } else {
        ftMode='count';
        ftChart.data.datasets[0].data=countData;
        ftChart.options.plugins.title.text='File Types (by count)';
        btn.textContent='by size';
      }
      ftChart.update();
    });}
  }

  /* 4. Creation timeline */
  var tl=analyticsData.creation_timeline;
  if(tl.length && document.getElementById('chart-timeline')){
    new Chart(document.getElementById('chart-timeline'),{
      type:'line',
      data:{
        labels:tl.map(function(e){return e.date;}),
        datasets:[
          {label:'Files',data:tl.map(function(e){return e.duplicate_files;}),
           borderColor:'rgba(52,152,219,1)',backgroundColor:'rgba(52,152,219,0.1)',fill:true,tension:0.3}
        ]
      },
      options:{
        responsive:true,
        maintainAspectRatio:false,
        plugins:{title:{display:true,text:'Creation Timeline'}},
        scales:{y:{beginAtZero:true,ticks:{precision:0}}}
      }
    });
  }
})();
"""


# ---------------------------------------------------------------------------
# Dry-run summary
# ---------------------------------------------------------------------------


def _html_dry_run_summary(dry_run_summary: DeletionSummary) -> str:
    parts: list[str] = ['<div class="dry-run-box">', "<h2>Dry-run summary</h2>"]
    parts.append(
        f"<p><strong>{len(dry_run_summary.deleted)}</strong> file(s) would be deleted, "
        f"freeing <strong>{_escape(format_size_human(dry_run_summary.bytes_freed))}</strong>.</p>"
    )
    if dry_run_summary.deleted:
        parts.append("<ul>")
        for p in dry_run_summary.deleted:
            parts.append(f"<li><code>{_escape(str(p))}</code></li>")
        parts.append("</ul>")
    parts.append("</div>\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Pair-mode HTML
# ---------------------------------------------------------------------------


def _html_pair_table(
    pairs: list[ScoredPair],
    thumbnails: dict[Path, str],
    *,
    keep_strategy: str | None = None,
    verbose: bool = False,
    mode: str = Mode.VIDEO,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> str:
    show_duration = mode != Mode.IMAGE
    show_resolution = mode != Mode.AUDIO

    parts: list[str] = ['<div class="table-wrap">', "<table>", "<thead><tr>"]
    headers = [
        ("#", False),
        ("Thumb A", False),
        ("File A", True),
        ("Size A", True),
    ]
    if show_duration:
        headers.append(("Duration A", True))
    if show_resolution:
        headers.append(("Resolution A", True))
    headers += [
        ("Thumb B", False),
        ("File B", True),
        ("Size B", True),
    ]
    if show_duration:
        headers.append(("Duration B", True))
    if show_resolution:
        headers.append(("Resolution B", True))
    headers += [
        ("Score", True),
        ("Breakdown", False),
    ]
    if keep_strategy:
        headers.append(("Keep", False))

    for label, sortable in headers:
        cls = ' class="sortable"' if sortable else ""
        parts.append(f"<th{cls}>{_escape(label)}</th>")
    parts.append("</tr></thead>\n<tbody>")

    for idx, pair in enumerate(pairs, 1):
        keep = (
            pick_keep(pair, keep_strategy, sidecar_extensions=sidecar_extensions, no_sidecars=no_sidecars)
            if keep_strategy
            else None
        )

        thumb_a = _get_thumbnail(pair.file_a, thumbnails)
        thumb_b = _get_thumbnail(pair.file_b, thumbnails)

        a_path = str(pair.file_a.path)
        b_path = str(pair.file_b.path)
        a_display = pair.file_a.path.name if not verbose else a_path
        b_display = pair.file_b.path.name if not verbose else b_path

        if verbose and pair.detail:
            breakdown = _escape(_format_breakdown_verbose(pair))
        else:
            bd_parts: list[str] = []
            for name, val in pair.breakdown.items():
                bd_parts.append(f"{name}: n/a" if val is None else f"{name}: {val:.1f}")
            breakdown = _escape(" | ".join(bd_parts))

        score_cls = _score_css_class(pair.total_score)

        parts.append("<tr>")
        parts.append(f'<td data-sort-value="{idx}">{idx}</td>')
        parts.append(f'<td><img class="thumb" src="{thumb_a}" alt=""></td>')

        a_ref = ' <span class="ref-tag">REF</span>' if pair.file_a.is_reference else ""
        a_keep_tag = ' <span class="keep-tag">KEEP</span>' if keep == "a" else ""
        parts.append(
            f'<td class="path-cell" data-sort-value="{_escape(a_path)}" title="{_escape(a_path)}">'
            f"{_escape(a_display)}{a_ref}{a_keep_tag}</td>"
        )

        parts.append(
            f'<td data-sort-value="{pair.file_a.file_size}">{_escape(format_size_human(pair.file_a.file_size))}</td>'
        )

        if show_duration:
            dur_a = pair.file_a.duration or 0
            parts.append(f'<td data-sort-value="{dur_a}">{_escape(_format_duration(pair.file_a.duration))}</td>')

        if show_resolution:
            res_a_sort = (pair.file_a.width or 0) * (pair.file_a.height or 0)
            res_a_text = _escape(_format_resolution(pair.file_a.width, pair.file_a.height))
            parts.append(f'<td data-sort-value="{res_a_sort}">{res_a_text}</td>')

        parts.append(f'<td><img class="thumb" src="{thumb_b}" alt=""></td>')

        b_ref = ' <span class="ref-tag">REF</span>' if pair.file_b.is_reference else ""
        b_keep_tag = ' <span class="keep-tag">KEEP</span>' if keep == "b" else ""
        parts.append(
            f'<td class="path-cell" data-sort-value="{_escape(b_path)}" title="{_escape(b_path)}">'
            f"{_escape(b_display)}{b_ref}{b_keep_tag}</td>"
        )

        parts.append(
            f'<td data-sort-value="{pair.file_b.file_size}">{_escape(format_size_human(pair.file_b.file_size))}</td>'
        )

        if show_duration:
            dur_b = pair.file_b.duration or 0
            parts.append(f'<td data-sort-value="{dur_b}">{_escape(_format_duration(pair.file_b.duration))}</td>')

        if show_resolution:
            res_b_sort = (pair.file_b.width or 0) * (pair.file_b.height or 0)
            res_b_text = _escape(_format_resolution(pair.file_b.width, pair.file_b.height))
            parts.append(f'<td data-sort-value="{res_b_sort}">{res_b_text}</td>')

        parts.append(
            f'<td data-sort-value="{pair.total_score}">'
            f'<span class="score-badge {score_cls}">{pair.total_score:.1f}</span></td>'
        )

        parts.append(f'<td class="breakdown">{breakdown}</td>')

        if keep_strategy:
            keep_text = "A" if keep == "a" else ("B" if keep == "b" else "-")
            parts.append(f"<td>{_escape(keep_text)}</td>")

        parts.append("</tr>\n")

    parts.append("</tbody></table></div>\n")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Group-mode HTML
# ---------------------------------------------------------------------------


def _html_group_sections(
    groups: list[DuplicateGroup],
    thumbnails: dict[Path, str],
    *,
    keep_strategy: str | None = None,
    verbose: bool = False,
    mode: str = Mode.VIDEO,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
) -> str:
    show_duration = mode != Mode.IMAGE
    show_resolution = mode != Mode.AUDIO
    parts: list[str] = []

    for i, group in enumerate(groups):
        open_attr = " open" if i == 0 else ""
        score_range = (
            f"{group.min_score:.1f}\u2013{group.max_score:.1f}"
            if group.min_score != group.max_score
            else f"{group.max_score:.1f}"
        )

        parts.append(f"<details{open_attr}>")
        parts.append(
            f"<summary>Group {group.group_id} &mdash; {len(group.members)} files "
            f"&mdash; Score: {_escape(score_range)} "
            f"(avg {group.avg_score:.1f})</summary>\n"
        )
        parts.append('<div class="group-content">')

        keep_path: Path | None = None
        if keep_strategy:
            keeper = pick_keep_from_group(
                group.members,
                keep_strategy,
                sidecar_extensions=sidecar_extensions,
                no_sidecars=no_sidecars,
            )
            if keeper is not None:
                keep_path = keeper.path

        parts.append("<table><thead><tr>")
        headers = ["#", "Thumb", "File", "Size"]
        if show_duration:
            headers.append("Duration")
        if show_resolution:
            headers.append("Resolution")
        for h in headers:
            parts.append(f"<th>{_escape(h)}</th>")
        parts.append("</tr></thead>\n<tbody>")

        for idx, member in enumerate(group.members, 1):
            thumb = _get_thumbnail(member, thumbnails)
            m_path = str(member.path)
            m_display = member.path.name if not verbose else m_path

            ref_tag = ' <span class="ref-tag">REF</span>' if member.is_reference else ""
            keep_tag = ' <span class="keep-tag">KEEP</span>' if keep_path and member.path == keep_path else ""

            parts.append("<tr>")
            parts.append(f"<td>{idx}</td>")
            parts.append(f'<td><img class="thumb" src="{thumb}" alt=""></td>')
            parts.append(
                f'<td class="path-cell" title="{_escape(m_path)}">{_escape(m_display)}{ref_tag}{keep_tag}</td>'
            )
            parts.append(f"<td>{_escape(format_size_human(member.file_size))}</td>")
            if show_duration:
                parts.append(f"<td>{_escape(_format_duration(member.duration))}</td>")
            if show_resolution:
                parts.append(f"<td>{_escape(_format_resolution(member.width, member.height))}</td>")
            parts.append("</tr>\n")

        parts.append("</tbody></table>")

        # Pair scores within group
        if group.pairs:
            parts.append('<div style="margin-top:12px"><strong>Pair scores:</strong></div>')
            parts.append('<table style="margin-top:4px"><thead><tr><th>File A</th><th>File B</th><th>Score</th>')
            if verbose:
                parts.append("<th>Breakdown</th>")
            parts.append("</tr></thead>\n<tbody>")
            for pair in group.pairs:
                score_cls = _score_css_class(pair.total_score)
                a_name = _escape(pair.file_a.path.name)
                b_name = _escape(pair.file_b.path.name)
                parts.append(
                    f"<tr><td>{a_name}</td><td>{b_name}</td>"
                    f'<td><span class="score-badge {score_cls}">{pair.total_score:.1f}</span></td>'
                )
                if verbose:
                    parts.append(f'<td class="breakdown">{_escape(_format_breakdown_verbose(pair))}</td>')
                parts.append("</tr>\n")
            parts.append("</tbody></table>")

        parts.append("</div></details>\n")

    return "".join(parts)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_MODE_TITLES: dict[str, str] = {
    "video": "Potential Duplicate Videos",
    "image": "Potential Duplicate Images",
    "audio": "Potential Duplicate Audio Files",
    "auto": "Potential Duplicate Media",
}


def _assemble_html_report(
    content_html: str,
    *,
    file: TextIO | None = None,
    title: str,
    stats: PipelineStats | None = None,
    pair_count: int,
    group_count: int | None = None,
    mode: str = Mode.VIDEO,
    dry_run_summary: DeletionSummary | None = None,
    analytics: AnalyticsResult | None = None,
) -> None:
    """Assemble and write a complete HTML report from pre-rendered content."""
    sections: list[str] = [_html_head(title)]
    sections.append(_html_summary_dashboard(stats, pair_count=pair_count, group_count=group_count, mode=mode))
    if analytics is not None:
        sections.append(_html_analytics_dashboard(analytics))
    if content_html:
        sections.append(content_html)
    else:
        sections.append('<div class="no-results">No duplicates found above threshold.</div>\n')
    if dry_run_summary is not None and dry_run_summary.deleted:
        sections.append(_html_dry_run_summary(dry_run_summary))
    sections.append(_html_foot())
    dest = file if file is not None else sys.stdout
    dest.write("".join(sections))


def write_html(
    pairs: list[ScoredPair],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    verbose: bool = False,
    stats: PipelineStats | None = None,
    mode: str = Mode.VIDEO,
    dry_run_summary: DeletionSummary | None = None,
    quiet: bool = False,
    pause_controller: PipelineController | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
    analytics: AnalyticsResult | None = None,
) -> None:
    """Write a self-contained HTML report for pair-mode results."""
    title = _MODE_TITLES.get(mode, "Potential Duplicates")
    all_meta = _collect_pair_metadata(pairs)
    thumbnails = _generate_all_thumbnails(all_meta, mode=mode, quiet=quiet, controller=pause_controller)
    content = (
        _html_pair_table(
            pairs,
            thumbnails,
            keep_strategy=keep_strategy,
            verbose=verbose,
            mode=mode,
            sidecar_extensions=sidecar_extensions,
            no_sidecars=no_sidecars,
        )
        if pairs
        else ""
    )
    _assemble_html_report(
        content,
        file=file,
        title=title,
        stats=stats,
        pair_count=len(pairs),
        mode=mode,
        dry_run_summary=dry_run_summary,
        analytics=analytics,
    )


def write_group_html(
    groups: list[DuplicateGroup],
    *,
    file: TextIO | None = None,
    keep_strategy: str | None = None,
    verbose: bool = False,
    stats: PipelineStats | None = None,
    mode: str = Mode.VIDEO,
    dry_run_summary: DeletionSummary | None = None,
    quiet: bool = False,
    pause_controller: PipelineController | None = None,
    sidecar_extensions: str | None = None,
    no_sidecars: bool = False,
    analytics: AnalyticsResult | None = None,
) -> None:
    """Write a self-contained HTML report for group-mode results."""
    title = _MODE_TITLES.get(mode, "Potential Duplicates")
    all_meta = _collect_group_metadata(groups)
    thumbnails = _generate_all_thumbnails(all_meta, mode=mode, quiet=quiet, controller=pause_controller)
    content = (
        _html_group_sections(
            groups,
            thumbnails,
            keep_strategy=keep_strategy,
            verbose=verbose,
            mode=mode,
            sidecar_extensions=sidecar_extensions,
            no_sidecars=no_sidecars,
        )
        if groups
        else ""
    )
    _assemble_html_report(
        content,
        file=file,
        title=title,
        stats=stats,
        pair_count=sum(len(g.pairs) for g in groups),
        group_count=len(groups),
        mode=mode,
        dry_run_summary=dry_run_summary,
        analytics=analytics,
    )
