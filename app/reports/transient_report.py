"""Ekspor Transient Study: workbook Excel & laporan Word (DOCX).

Isi mengikuti struktur bab "Dynamic and Transient Performance" + "Short
Circuit and Protection Studies" pada proposal teknis: model & data, hasil per
kasus (tabel + grafik), ringkasan hasil → persyaratan desain, tingkat hubung
singkat per konfigurasi, dan kajian pemutusan feeder.
"""
from __future__ import annotations

import io
import math

import numpy as np

CASE_COLS = [
    ('id', 'ID'), ('group', 'Group'), ('title', 'Case'),
    ('scenario', 'Pre-event operating point'), ('status', 'Result')]
METRIC_COLS = [
    ('f_pre', 'f pre (Hz)', 2), ('f_min', 'f min (Hz)', 2),
    ('f_max', 'f max (Hz)', 2), ('f_end', 'f end (Hz)', 2),
    ('rocof', 'RoCoF 100 ms (Hz/s)', 2), ('v_min', 'V min (pu)', 3),
    ('v_1s', 'V at 1 s (pu)', 3), ('v_end', 'V end (pu)', 3),
    ('phase_jump_deg', 'Phase jump (°)', 1),
    ('pcs_ipk', 'PCS peak (pu)', 2), ('pcs_t_lim', 'PCS at limit (s)', 2),
    ('pcs_end', 'PCS end (pu)', 2), ('lost_kw', 'Lost / step (kW)', 0),
    ('q_peak_kvar', 'Q peak (kvar)', 0), ('q_t90', 'Q response t90 (s)', 3),
    ('mode_hz', 'Mode (Hz)', 2), ('damping', 'Damping ratio', 2),
    ('t_decay', 'Decay to 10 % (s)', 2), ('bess_share', 'BESS share of step', 2),
    ('motor_ipk_a', 'Motor peak (A)', 0), ('t_runup', 'Run-up (s)', 2),
    ('unit_ipk_a', 'Unit peak (A)', 0), ('unit_swing_kw', 'Unit swing (kW)', 0),
    ('i_fault_ka', 'Fault current (kA)', 2), ('v_fault', 'V in fault (pu)', 3),
    ('motor_w_min', 'Motor speed min (pu)', 3),
    ('t_v_recover', 'V > 0.9 pu after (s)', 3)]


def _num(v, dec):
    if v is None or isinstance(v, bool):
        return ''
    try:
        v = float(v)
    except (TypeError, ValueError):
        return ''
    if not math.isfinite(v):
        return ''
    return round(v, dec)


def case_rows(study: dict):
    """-> (header, rows) tabel kasus lengkap (kolom metrik kosong dibuang)."""
    used = [m for m in METRIC_COLS
            if any(_num(c['metrics'].get(m[0]), m[2]) != '' for c in study['cases'])]
    head = ([h for _k, h in CASE_COLS] + ['Basis of the result']
            + [m[1] for m in used])
    from ..engine.transient_cases import case_evidence
    crit = study.get('crit') or {}
    rows = []
    for c in study['cases']:
        r = [str(c.get(k, '')).replace('GRID', 'Utility Grid')
             for k, _h in CASE_COLS]
        try:
            r.append(case_evidence(c, crit)[1])
        except Exception:
            r.append('; '.join(c.get('reasons') or []))
        r += [_num(c['metrics'].get(k), d) for k, _h, d in used]
        rows.append(r)
    return head, rows


def evidence_rows(study: dict) -> list:
    """[ID, Case, Result, Criterion, Measured, Limit, Status, Basis] untuk
    seluruh kasus — bukti penilaian Pass/Fail per kriteria."""
    from ..engine.transient_cases import case_evidence
    crit = study.get('crit') or {}
    out = []
    for c in study['cases']:
        try:
            checks, _e = case_evidence(c, crit)
        except Exception:
            continue
        for x in checks:
            out.append([c['id'], c['title'], c['status'], x['criterion'],
                        x['measured'], x['limit'], x['status'], x['basis']])
    return out


# ---------------------------------------------------------------- Excel
def _write_pqa_sheets(xw, q: dict):
    import pandas as pd
    pd.DataFrame([(k, (', '.join(f'{x:,.0f}' if isinstance(x, (int, float))
                                 else str(x) for x in v)
                       if isinstance(v, list) else v))
                  for k, v in q.items()
                  if not isinstance(v, dict) and k not in (
                      'window_kvar', 'analysis', 'series', 'p_by_hour')
                  and not (isinstance(v, list) and v
                           and isinstance(v[0], dict))],
                 columns=['PQA item', 'Value']).to_excel(
        xw, sheet_name='PQA', index=False)
    if q.get('analysis'):
        from ..data.pqa import analysis_rows
        pd.DataFrame(analysis_rows(q), columns=[
            'Analysis', 'Item', 'Value', 'Unit', 'Reference / limit',
            'Result']).to_excel(xw, sheet_name='PQA Analysis',
                                index=False)
        for _k, _s in (q.get('series') or {}).items():
            _d = {'t (%s)' % q.get('t_unit', 'h'): _s['t']}
            _d.update(_s['y'])
            pd.DataFrame(_d).to_excel(
                xw, sheet_name=('PQA ' + _k)[:31], index=False)


def export_pqa_xlsx(path: str, q: dict) -> str:
    """Ekspor hasil analisis PQA saja (tanpa studi transient)."""
    import pandas as pd
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        _write_pqa_sheets(xw, q)
    return path


def export_xlsx(path: str, study: dict, cfg: dict | None = None) -> str:
    import pandas as pd
    cfg = cfg or {}
    with pd.ExcelWriter(path, engine='openpyxl') as xw:
        info = [('Project', cfg.get('project_name', '')),
                ('Site', cfg.get('site_name', '') or cfg.get('location', '')),
                ('Nominal frequency (Hz)', study['f_nom']),
                ('Bus voltage (kV)', study['v_kv']),
                ('System covered by the sheets without suffix',
                 study.get('system', 'All configured sources')),
                ('Study load (kW)', study['load_kw']),
                ('Largest DOL motor (kW)', study['motor_kw']),
                ('Largest DOL motor — basis', study.get('motor_basis', '')),
                ('Base operating point', study['base_scenario']),
                ('Model', 'Single-bus RMS (phasor) model, 1 ms time step'),
                ('', ''),
                ('Criterion: frequency band (Hz)',
                 f"{study['crit']['f_lo']:g} – {study['crit']['f_hi']:g}"),
                ('Criterion: voltage minimum (pu)', study['crit']['v_lo']),
                ('Criterion: RoCoF (Hz/s)', study['crit']['rocof'])]
        pd.DataFrame(info, columns=['Item', 'Value']).to_excel(
            xw, sheet_name='Info', index=False)
        pd.DataFrame(study['sources'], columns=[
            'Element', 'Rating', 'Rated current', 'Representation',
            'Parameters']).to_excel(xw, sheet_name='Model', index=False)
        head, rows = case_rows(study)
        pd.DataFrame(rows, columns=head).to_excel(
            xw, sheet_name='Cases', index=False)
        pd.DataFrame(evidence_rows(study), columns=[
            'ID', 'Case', 'Result', 'Criterion', 'Measured', 'Limit', 'Status',
            'Basis / reason']).to_excel(xw, sheet_name='Evidence', index=False)
        if study.get('basis'):
            pd.DataFrame(study['basis'], columns=[
                'Parameter', 'Value', 'Unit', 'Standard basis of the default']
            ).to_excel(xw, sheet_name='Parameter Basis', index=False)
        q = (cfg or {}).get('tr_pqa') or study.get('pqa')
        if isinstance(q, dict):
            _write_pqa_sheets(xw, q)
        pd.DataFrame(study['requirements'], columns=[
            'Event', 'Result', 'Requirement that follows']).to_excel(
            xw, sheet_name='Requirements', index=False)
        pd.DataFrame([[s['config'], round(s['ik_max'], 2), round(s['ip'], 2),
                       round(s['ik_min'], 2)] for s in study['sc']], columns=[
            'Operating configuration', 'Maximum initial fault I″k (kA)',
            'Peak ip (kA)', 'Minimum fault (kA)']).to_excel(
            xw, sheet_name='Short Circuit', index=False)
        pd.DataFrame([[s['name'], _num(s['ir_a'], 0), s['basis'],
                       round(s['ik_sub'], 2), round(s['ik_tr'], 2)]
                      for s in study['sc_sources']], columns=[
            'Source', 'Rated current (A)', 'Basis',
            'Initial contribution (kA)', 'Sustained / transient (kA)']
        ).to_excel(xw, sheet_name='SC Sources', index=False)
        pd.DataFrame([[p['rating'], p['lo'], p['hi'],
                       {'yes': 'Yes', 'partial': 'Only at low pickup setting',
                        'no': 'No'}[p['verdict']]] for p in study['protection']],
                     columns=['Feeder rating (A)', 'Instantaneous pickup 5×In (kA)',
                              'Instantaneous pickup 10×In (kA)',
                              f"Clears instantaneously at {study['ik_weak']:.2f} kA?"]
                     ).to_excel(xw, sheet_name='Feeder Clearing', index=False)
        # v168 — multi-sistem: perbandingan, penilaian PQA, kasus tiap sistem
        from ..engine.transient_cases import scenario_studies
        if study.get('comparison'):
            pd.DataFrame(study['comparison']['rows'],
                         columns=study['comparison']['head']).to_excel(
                xw, sheet_name='Systems', index=False)
        if study.get('assessment'):
            pd.DataFrame(study['assessment']['rows'],
                         columns=study['assessment']['head']).to_excel(
                xw, sheet_name='PQA Assessment', index=False)
        _abbr = {'Existing': 'Ex', 'New': 'New', 'Existing + New': 'Ex+New'}
        for nm, s2 in scenario_studies(study):
            if s2 is study:
                continue
            a_ = _abbr.get(nm, nm[:8])
            h2, r2 = case_rows(s2)
            pd.DataFrame(r2, columns=h2).to_excel(
                xw, sheet_name=f'Cases {a_}'[:31], index=False)
            pd.DataFrame(s2['requirements'], columns=[
                'Event', 'Result', 'Requirement that follows']).to_excel(
                xw, sheet_name=f'Requirements {a_}'[:31], index=False)
            pd.DataFrame([[x['config'], round(x['ik_max'], 2), round(x['ip'], 2),
                           round(x['ik_min'], 2)] for x in s2['sc']], columns=[
                'Operating configuration', 'Maximum initial fault I″k (kA)',
                'Peak ip (kA)', 'Minimum fault (kA)']).to_excel(
                xw, sheet_name=f'Short Circuit {a_}'[:31], index=False)
        for c in study['cases']:
            s = c.get('series') or {}
            if 't' not in s:
                continue
            df = pd.DataFrame({_series_label(k): np.asarray(v, float)
                               for k, v in s.items()})
            df.to_excel(xw, sheet_name=f"TS {c['id']}"[:31], index=False)
        for ws in xw.book.worksheets:
            for col in ws.columns:
                w = max((len(str(x.value)) for x in col[:60]
                         if x.value is not None), default=8)
                ws.column_dimensions[col[0].column_letter].width = min(max(10, w + 2), 70)
    return path


def _series_label(k: str) -> str:
    if k == 't':
        return 'Time (s)'
    if k == 'f':
        return 'Frequency (Hz)'
    if k == 'v':
        return 'Bus voltage (pu)'
    if k == 'p_load':
        return 'Static load (kW)'
    if k == 'i_BESS':
        return 'PCS loading (pu)'
    if k == 'q_load':
        return 'Load Q (kvar)'
    if k.startswith('q_'):
        return f"{k[2:].replace('GRID', 'Utility Grid')} Q (kvar)"
    if k == 'i_fault':
        return 'Fault current (A)'
    if k.startswith('p_'):
        return f"{k[2:].replace('GRID', 'Utility Grid')} P (kW)"
    if k.startswith('i_mot'):
        return f'Motor {k[5:]} current (A)'
    if k.startswith('w_mot'):
        return f'Motor {k[5:]} speed (pu)'
    if k.startswith('i_'):
        return f"{k[2:].replace('GRID', 'Utility Grid')} current (A)"
    return k


# ---------------------------------------------------------------- grafik
def case_figure(c: dict, f_nom: float = 50.0, dpi: int = 130) -> bytes | None:
    """PNG tiga panel (frekuensi, tegangan, daya/pembebanan) satu kasus."""
    s = c.get('series') or {}
    if 't' not in s:
        return None
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    t = np.asarray(s['t'], float)
    fig, ax = plt.subplots(4, 1, figsize=(7.2, 7.6), sharex=True)
    ax[0].plot(t, s['f'], color='#2563EB', lw=1.2)
    ax[0].set_ylabel('Frequency (Hz)')
    ax[1].plot(t, s['v'], color='#DC2626', lw=1.2)
    ax[1].set_ylabel('Bus voltage (pu)')
    pal = ['#B45309', '#DC2626', '#7C3AED', '#0EA5E9', '#84CC16', '#06B6D4',
           '#2563EB', '#DB2777']
    i = 0
    for k, v in s.items():
        if k.startswith('p_') and k != 'p_load':
            ax[2].plot(t, v, lw=1.1, color=pal[i % len(pal)],
                       label=k[2:].replace('GRID', 'Utility Grid'))
            i += 1
    ax[2].set_ylabel('Active power (kW)')
    if 'i_BESS' in s and np.max(np.abs(s['i_BESS'])) > 0:
        a2 = ax[2].twinx()
        a2.plot(t, s['i_BESS'], color='#111827', lw=0.9, ls='--',
                label='PCS loading (pu)')
        a2.set_ylabel('PCS loading (pu)')
        a2.legend(loc='lower right', fontsize=7, frameon=False)
    ax[2].legend(loc='upper right', fontsize=7, ncol=3, frameon=False)
    i = 0
    for k, v in s.items():
        if k.startswith('q_') and k != 'q_load':
            ax[3].plot(t, v, lw=1.1, color=pal[i % len(pal)],
                       label=k[2:].replace('GRID', 'Utility Grid'))
            i += 1
    ax[3].set_ylabel('Reactive power (kvar)')
    if i:
        ax[3].legend(loc='upper right', fontsize=7, ncol=3, frameon=False)
    ax[3].set_xlabel('Time (s)')
    for a in ax:
        a.grid(alpha=0.25)
        a.axvline(c.get('t_ev', 1.0), color='#9CA3AF', lw=0.7, ls=':')
    ax[0].set_title(f"{c['id']} — {c['title']}", fontsize=9)
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


def pqa_figure(q: dict, key: str, dpi: int = 130) -> bytes | None:
    """Grafik deret PQA (hasil pengukuran) untuk satu analisis."""
    s = (q.get('series') or {}).get(key)
    if not s:
        return None
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7.2, 2.9))
    t = np.asarray(s['t'], float)
    for name, y in s['y'].items():
        ax.plot(t, np.asarray([np.nan if v is None else v for v in y], float),
                lw=0.9, label=name)
    for h in s.get('hlines') or []:
        ax.axhline(float(h), color='#DC2626', lw=0.8, ls='--')
    ax.set_ylabel(s.get('ylabel', ''), fontsize=8)
    ax.set_xlabel('Time (h from start of record)' if q.get('t_unit') == 'h'
                  else 'Sample', fontsize=8)
    ax.grid(alpha=0.25); ax.tick_params(labelsize=7)
    ax.legend(fontsize=6, ncol=3, loc='best')
    fig.tight_layout()
    buf = io.BytesIO()
    fig.savefig(buf, format='png', dpi=dpi)
    plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------- DOCX
def export_docx(path: str, study: dict, cfg: dict | None = None) -> str:
    from docx import Document
    from docx.shared import Pt, Cm, RGBColor
    from docx.enum.section import WD_ORIENT
    cfg = cfg or {}
    doc = Document()
    st = doc.styles['Normal']
    st.font.name = 'Calibri'; st.font.size = Pt(10)

    def table(head, rows, widths=None, size=8):
        tb = doc.add_table(rows=1, cols=len(head))
        tb.style = 'Light Grid Accent 1'
        for i, h in enumerate(head):
            cell = tb.rows[0].cells[i]
            cell.text = ''
            r = cell.paragraphs[0].add_run(str(h)); r.bold = True
            r.font.size = Pt(size)
        for row in rows:
            cells = tb.add_row().cells
            for i, v in enumerate(row):
                cells[i].text = ''
                r = cells[i].paragraphs[0].add_run('' if v is None else str(v))
                r.font.size = Pt(size)
                if str(v) == 'Fail':
                    r.font.color.rgb = RGBColor(0xC0, 0x1C, 0x1C); r.bold = True
        if widths:
            for row in tb.rows:
                for i, w in enumerate(widths):
                    if i < len(row.cells):
                        row.cells[i].width = Cm(w)
        doc.add_paragraph()
        return tb

    name = cfg.get('project_name', '') or 'Hybrid Power Plant'
    doc.add_heading('Dynamic and Transient Performance Study', 0)
    doc.add_paragraph(f"{name}" + (f" — {cfg.get('site_name')}" if cfg.get('site_name') else ''))
    doc.add_heading('1. Scope and method', 1)
    doc.add_paragraph(
        'This study uses a single-bus RMS (phasor) model with 1 ms time steps. All '
        'sources and loads are on the main busbar; quantities are per unit on '
        f"1,000 kVA at {study['v_kv']:g} kV, {study['f_nom']:g} Hz. The model covers "
        'electromechanical and voltage behaviour from about 10 ms to several '
        'minutes: frequency, voltage, power sharing, converter current limiting, '
        'motor acceleration, synchronising transients and oscillations between '
        'sources. Sub-cycle effects (switching, harmonics, DC offset of fault and '
        'inrush currents) need the supplier EMT model and are outside this study.')
    doc.add_paragraph(
        f"Study load {study['load_kw']:,.0f} kW; largest direct-on-line motor "
        f"{study['motor_kw']:,.0f} kW. Base operating point: {study['base_scenario']}. "
        f"Acceptance criteria: frequency {study['crit']['f_lo']:g}–"
        f"{study['crit']['f_hi']:g} Hz, voltage ≥ {study['crit']['v_lo']:g} pu "
        f"(outside faults), RoCoF ≤ {study['crit']['rocof']:g} Hz/s (first 100 ms), "
        'no converter trip, PCS loading within its continuous rating after the event.')
    if study.get('pqa'):
        q = study['pqa']
        doc.add_paragraph(
            f"Measured load data (PQA, {q.get('source', '')}): {q.get('n', 0):,} samples"
            + (f" at {q['dt_s']:g} s" if q.get('dt_s') else '')
            + f"; maximum {q['p_max']:,.0f} kW, 95th percentile {q['p_p95']:,.0f} kW, "
            f"mean {q['p_mean']:,.0f} kW"
            + (f"; power factor {q['pf']:.3f}" if q.get('pf') else '')
            + (f"; largest load change between samples +{q['step_up_kw']:,.0f} / "
               f"{q['step_dn_kw']:,.0f} kW" if 'step_up_kw' in q else '')
            + '. The study load, load power factor and load-step cases use these '
              'measured values.')
    from ..engine.transient_cases import scenario_studies
    _others = [(nm, s2) for nm, s2 in scenario_studies(study) if s2 is not study]
    if study.get('comparison') and len(study['comparison']['head']) > 2:
        doc.add_heading('Systems analysed', 2)
        doc.add_paragraph(
            'The study covers ' + ', '.join(study['comparison']['head'][1:])
            + '. Sections 2 to 6 give the detailed results of the '
            f"{study.get('system', '')} system; the cases and requirements of "
            'the other systems are in the section "Other analysed systems".')
        table(study['comparison']['head'], study['comparison']['rows'], size=7)
    if study.get('motor_basis'):
        doc.add_paragraph('Largest DOL motor basis: ' + study['motor_basis'] + '.')
    if study.get('assessment'):
        a_ = study['assessment']
        doc.add_heading('Assessment against the measured data (PQA)', 2)
        doc.add_paragraph(
            'Every group of PQA columns is used: the measured load, power '
            'factor, load steps and current surge define the cases; measured '
            'dips, frequency, unbalance and harmonics are compared with, or '
            'scaled to, each system. ' + a_.get('note', ''))
        table(a_['head'], a_['rows'], size=6)
    doc.add_heading('2. Model and data', 1)
    table(['Element', 'Rating', 'Rated current', 'Representation', 'Parameters'],
          study['sources'], widths=[2.4, 2.0, 2.0, 5.6, 5.0])
    doc.add_paragraph(
        'Static load: P ∝ V^kpv · (1 + kpf · Δf/f), Q ∝ V²; constant impedance '
        'below 0.7 pu. Motors: induction-motor equivalent circuit (deep-bar rotor) '
        'with mechanical dynamics and quadratic load torque. The generic machine '
        'and converter parameters are design-basis values; they are replaced by '
        'vendor data and calibrated on site measurements in detailed engineering.')

    if study.get('basis'):
        doc.add_paragraph('Parameter values and the standard basis of each default:')
        table(['Parameter', 'Value', 'Unit', 'Standard basis of the default'],
              study['basis'], widths=[4.2, 1.8, 1.4, 9.6], size=7)
    doc.add_heading('3. Results by case', 1)
    groups = []
    for c in study['cases']:
        if c['group'] not in groups:
            groups.append(c['group'])
    for gi, g in enumerate(groups, 1):
        doc.add_heading(f'3.{gi} {g[3:] if len(g) > 3 and g[1] == "." else g}', 2)
        cs = [c for c in study['cases'] if c['group'] == g]
        used = [m for m in METRIC_COLS if any(
            _num(c['metrics'].get(m[0]), m[2]) != '' for c in cs)][:9]
        head = ['ID', 'Case'] + [m[1] for m in used] + ['Result']
        rows = [[c['id'], c['title']] + [_num(c['metrics'].get(k), d)
                                         for k, _h, d in used] + [c['status']]
                for c in cs]
        table(head, rows, size=7)
        from ..engine.transient_cases import case_evidence
        for c in cs:
            # v177 — dasar hasil Pass/Fail SELALU dicantumkan per kasus
            try:
                expl = case_evidence(c, study.get('crit') or {})[1]
            except Exception:
                expl = '; '.join(c.get('reasons') or [])
            p = doc.add_paragraph(style='List Bullet')
            p.add_run(f"{c['id']}: ").bold = True
            p.add_run(' '.join(x for x in (
                f"pre-event {c['scenario'].replace('GRID', 'Utility Grid')}."
                if c['scenario'] else '', expl.replace('GRID', 'Utility Grid'),
                ('Events: ' + '; '.join(c['log'][:4]) + '.') if c.get('log') else '')
                if x))
        fig_case = next((c for c in cs if c['status'] in ('Fail', 'Pass')), None)
        if fig_case is not None:
            png = case_figure(fig_case, study['f_nom'])
            if png:
                doc.add_picture(io.BytesIO(png), width=Cm(15.5))
                cp = doc.add_paragraph(
                    f"Figure 3-{gi}. {fig_case['id']} — {fig_case['title']}")
                cp.runs[0].italic = True

    doc.add_heading('4. Short circuit and protection', 1)
    doc.add_paragraph(
        'Fault levels at the main busbar by the IEC 60909 equivalent-source '
        'method, with converters as current-limited sources. Values are estimates '
        'from design-basis reactances; final settings come from the coordination '
        'study with vendor fault data.')
    table(['Source', 'Rated current (A)', 'Basis', 'Initial (kA)',
           'Sustained / transient (kA)'],
          [[s['name'], _num(s['ir_a'], 0), s['basis'], f"{s['ik_sub']:.2f}",
            f"{s['ik_tr']:.2f}"] for s in study['sc_sources']])
    table(['Operating configuration', 'Maximum initial fault (kA)', 'Peak ip (kA)',
           'Minimum fault for protection sensitivity (kA)'],
          [[s['config'], f"{s['ik_max']:.1f}", f"{s['ip']:.1f}",
            f"{s['ik_min']:.1f}"] for s in study['sc']])
    doc.add_paragraph(
        f"Feeder clearing at the minimum fault level ({study['weak_config']}, "
        f"{study['ik_weak']:.2f} kA):")
    table(['Feeder rating (A)', 'Instantaneous pickup 5–10 × In (kA)',
           'Clears instantaneously?'],
          [[p['rating'], f"{p['lo']:.2f} – {p['hi']:.2f}",
            {'yes': 'Yes', 'partial': 'Only at low pickup setting',
             'no': 'No'}[p['verdict']]] for p in study['protection']])

    doc.add_heading('5. Summary of results and requirements', 1)
    table(['Event', 'Result', 'Requirement that follows'],
          [list(r) for r in study['requirements']], widths=[3.2, 5.0, 8.8])
    doc.add_heading('6. Studies for detailed engineering', 1)
    table(['Study', 'Tool', 'Purpose'], [
        ['RMS dynamics, all cases above', 'PowerFactory, ETAP or PSS/E with vendor models',
         'Confirms the results with the actual converter control and generator data'],
        ['EMT', 'PSCAD or EMTP with vendor black-box model',
         'Fault-current wave shape, sub-cycle current limit, inrush, harmonics'],
        ['Load flow', 'Same as RMS', 'Feeder voltage drop in converter-only mode'],
        ['Short circuit and coordination', 'IEC 60909 plus converter fault model',
         'Protection settings and setting groups'],
        ['Field validation', 'Commissioning tests with event-capture PQ analyser',
         'Confirms model parameters']])
    if _others:
        doc.add_heading('Other analysed systems', 1)
        for nm, s2 in _others:
            doc.add_heading(f'System: {nm}', 2)
            if s2.get('not_viable'):
                doc.add_paragraph('Not analysed — ' + s2['not_viable'])
                continue
            doc.add_paragraph(
                f"Study load {s2['load_kw']:,.0f} kW. Base operating point: "
                f"{s2['base_scenario'].replace('GRID', 'Utility Grid')}. "
                f"Fault level {s2['ik_weak']:.2f}–{s2['ik_all']:.2f} kA.")
            h2, r2 = case_rows(s2)
            keep = [i for i, h in enumerate(h2) if h in (
                'ID', 'Case', 'Result', 'f min (Hz)', 'f max (Hz)',
                'V min (pu)', 'RoCoF 100 ms (Hz/s)', 'Basis of the result')]
            if not keep or len(keep) < 3:
                keep = list(range(min(len(h2), 8)))
            table([h2[i] for i in keep], [[x[i] for i in keep] for x in r2],
                  size=7)
            table(['Event', 'Result', 'Requirement that follows'],
                  [list(x) for x in s2['requirements']],
                  widths=[3.2, 5.0, 8.8], size=7)
    q = cfg.get('tr_pqa') or study.get('pqa')
    if isinstance(q, dict) and q.get('analysis'):
        doc.add_heading('7. Measured power quality (PQA)', 1)
        doc.add_paragraph(
            f"Source: {q.get('source', '')}; {q.get('n', 0):,} records"
            + (f" at {q['dt_s']:g} s" if q.get('dt_s') else '')
            + (f", {q['t_start']} to {q['t_end']}" if q.get('t_start') else '')
            + '. These are measurements of the existing system, shown next to '
              'the simulated cases; an analysis whose input columns were not '
              'recorded is listed as not performed.')
        for ai, a in enumerate(q['analysis'], 1):
            doc.add_heading(f"7.{ai} {a['title']}", 2)
            if a['status'] == 'skipped':
                doc.add_paragraph('Not performed — required columns missing: '
                                  + ', '.join(a['missing']) + '.')
                continue
            table(['Item', 'Value', 'Unit', 'Reference / limit', 'Result'],
                  [list(r) for r in a['rows']], widths=[5.2, 4.2, 1.4, 5.0, 1.2],
                  size=7)
            if a['missing']:
                doc.add_paragraph('Columns not available (related items '
                                  'omitted): ' + ', '.join(a['missing']) + '.')
            for nt in a.get('notes') or []:
                doc.add_paragraph(nt, style='List Bullet')
            png = pqa_figure(q, a['id'])
            if png:
                doc.add_picture(io.BytesIO(png), width=Cm(15.5))
                cp = doc.add_paragraph(f"Figure 7-{ai}. {a['title']}")
                cp.runs[0].italic = True
    doc.add_heading('References', 1)
    for r in REFERENCES:
        doc.add_paragraph(r, style='List Bullet')
    doc.save(path)
    return path


REFERENCES = [
    'IEC 61400-27-1:2020, Wind energy generation systems — Electrical simulation '
    'models — Generic models (Type 3 and Type 4 wind turbines).',
    'IEC 61400-1:2019, Wind energy generation systems — Design requirements '
    '(wind profile, extreme operating gust).',
    'IEC 61400-12-1:2022, Power performance measurements of electricity producing '
    'wind turbines (air-density normalisation).',
    'IEC 61400-21-1:2019, Measurement and assessment of electrical characteristics '
    '— Wind turbines.',
    'IEEE Std 2800-2022, Interconnection and interoperability of inverter-based '
    'resources (ride-through, reactive current, frequency response).',
    'IEEE Std 1110-2019, Guide for synchronous generator modeling practices in '
    'power system stability analyses.',
    'IEEE Std 421.5-2016, Recommended practice for excitation system models.',
    'IEEE PES-TR1 (2013), Dynamic models for turbine-governors in power system '
    'studies (TGOV1, IEEEG1, diesel governor).',
    'IEEE Std 122-1991, Recommended practice for functional and performance '
    'characteristics of control systems for steam turbine-generator units.',
    'IEC 60045-1:2020, Steam turbines — Specifications.',
    'ISO 8528-5:2022, Reciprocating internal combustion engine driven generating '
    'sets — Generating sets (performance classes, step load).',
    'IEC 60909-0:2016, Short-circuit currents in three-phase a.c. systems.',
    'IEC 60034-1 (Zone A/B voltage and frequency), IEC 60034-3, IEC 60034-4, '
    'IEC 60034-12 (starting performance).',
    'IEC 60038, IEC standard voltages; IEC 60196, IEC standard frequencies.',
    'IEC 60364-4-41, Protection against electric shock (disconnection times).',
    'IEC 60947-2 / IEC 60947-4-1, Low-voltage switchgear and controlgear.',
    'IEC 60228, Conductors of insulated cables.',
    'IEC 62116, Test procedure of islanding prevention measures.',
    'ISO 3977-2 / ISO 2314, Gas turbines — procurement and acceptance tests.',
    'IEC 62933-5-2:2020, Electrical energy storage systems — Safety requirements.',
    'IEC 61000-4-30, Power quality measurement methods (half-cycle RMS, dips, '
    'swells, interruptions, aggregation intervals).',
    'EN 50160, Voltage characteristics of electricity supplied by public '
    'networks; IEC 61000-2-2, Compatibility levels for low-frequency conducted '
    'disturbances (THD, individual harmonics, unbalance, frequency).',
    'IEEE Std 1159, Recommended practice for monitoring electric power quality; '
    'IEEE Std 519, Harmonic control in electric power systems.',
]
