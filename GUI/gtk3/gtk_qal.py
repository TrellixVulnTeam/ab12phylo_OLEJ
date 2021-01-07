# 2020 Leo Kaindl

import logging
import threading
from argparse import Namespace
from pathlib import Path
from time import sleep

import gi
import matplotlib.pyplot as plt
import numpy as np
from Bio import SeqIO
from matplotlib.backends.backend_gtk3agg import FigureCanvasGTK3Agg as FigureCanvas
from matplotlib.colors import ListedColormap
from matplotlib.figure import Figure

import static

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, Gdk, GObject

from static import PATHS
from GUI.gtk3 import shared, gtk_rgx

from ab12phylo.filter import trim_ends, mark_bad_stretches

LOG = logging.getLogger(__name__)
plt.set_loglevel('warning')
PAGE = 2

"""The page for ABI trace trimming. Very similar to the MSA trimming page gtk_gbl.py"""


def init(gui):
    data, iface = gui.data, gui.iface

    iface.rev_handler = iface.accept_rev.connect('toggled', parse, None, gui)
    iface.accept_nophred.set_active(True)
    iface.accept_nophred.connect('toggled', parse, None, gui)

    iface.min_phred.set_adjustment(Gtk.Adjustment(value=30, upper=60, lower=0,
                                                  step_increment=1, page_increment=1))
    iface.min_phred.set_numeric(True)
    iface.min_phred.set_update_policy(Gtk.SpinButtonUpdatePolicy.IF_VALID)

    # this is kept up-to-date by the signals below
    iface.qal = Namespace(gene_roll='all')

    for w_name in ['min_phred', 'trim_out', 'trim_of', 'bad_stretch']:
        wi = iface.__getattribute__(w_name)
        iface.qal.__setattr__(w_name, int(wi.get_text()))
        wi.connect('changed', edit, data, iface)
        wi.connect('focus_out_event', parse, gui)
        # wi.connect('activate', parse, None, gui)

    for w_name in ['accept_rev', 'accept_nophred']:
        iface.qal.__setattr__(w_name, iface.__getattribute__(w_name).get_active())

    for wi in [iface.trim_out, iface.trim_of, iface.bad_stretch]:
        wi.connect('key-press-event', keypress, data, iface)

    # init row annotation
    iface.view_qal.set_model(data.qal_model)
    iface.view_qal.set_headers_visible(False)
    iface.view_qal.append_column(Gtk.TreeViewColumn(
        title='id', cell_renderer=Gtk.CellRendererText(), text=0, underline=1, strikethrough=2))
    # crt = Gtk.CellRendererToggle(radio=False)
    # crt.props.indicator_size = 13
    # iface.view_qal.append_column(Gtk.TreeViewColumn(
    #     title='no phreds', active=1, cell_renderer=crt))

    sel = iface.view_qal.get_selection()
    sel.set_mode(Gtk.SelectionMode.MULTIPLE)
    sel.connect('changed', shared.keep_visible,
                iface.parallel_qal.props.vadjustment.props, iface.qal)
    iface.view_qal.connect('check-resize', shared.get_height_resize,
                           iface.qal_spacer, [iface.qal_win])
    # in-preview deletion
    iface.view_qal.connect('key_press_event', shared.delete_and_ignore_rows,
                           gui, PAGE, sel, iface.qal)
    iface.qal_eventbox.connect_after('button_press_event', shared.select_seqs, PAGE, iface.zoom,
                                     iface.view_qal, iface.qal)  # in-preview selection
    iface.qal_win.connect('scroll-event', shared.xy_scale, gui, PAGE)  # zooming


def refresh(gui):
    data, iface = gui.data, gui.iface
    if not (gui.wd / PATHS.preview).exists() or 0 in data.qal_shape:
        start_trim(gui)
        return

    # place the png preview
    shared.load_image(iface.zoom, PAGE, iface.qal_eventbox, gui.wd / PATHS.preview,
                      data.qal_shape[0] * shared.get_hadj(iface), data.qal_shape[1])
    shared.load_colorbar(iface.palplot, gui.wd)
    gui.win.show_all()


def parse(widget, event, gui):
    """
    Parse the content of a widget. Hitting enter in an entry still calls this, which is good.
    :param widget: The element to parse and inspect for changes
    :param event: passed by some signals -> focus_out_event
    :param gui:
    :return:
    """
    data, iface = gui.data, gui.iface
    LOG.debug('parsing for re-draw')
    pre = None
    try:
        pre = iface.qal.__getattribute__(widget.get_name())
    except KeyError:
        exit('%s not in q_params' % widget.get_name())
    # getting new value depends on widget type
    if widget == iface.gene_roll:
        now = widget.get_active_text()
    elif widget in [iface.accept_rev, iface.accept_nophred]:
        now = widget.get_active()
    else:
        try:
            now = int(widget.get_text())
        except ValueError:
            now = 0
    delete_event(widget, event)

    # cause re-drawing if something changed
    if pre == now:
        LOG.debug('no change, skip re-draw')
        return
    iface.qal.__setattr__(widget.get_name(), now)
    if iface.qal.trim_out > iface.qal.trim_of:
        shared.show_notification(gui, 'cannot draw %d from %d' %
                                 (iface.qal.trim_out, iface.qal.trim_of))
        widget.set_text('0')
    else:
        shared.set_changed(gui, PAGE)
        # start_trim(gui)


def start_trim(gui):
    """
    For non-empty gene set, start a background re-drawing thread
    and return the GUI to the main loop.
    :param gui:
    :return:
    """
    data, iface = gui.data, gui.iface
    # called after files are read
    if not data.genes or iface.running or iface.notebook.get_current_page() != PAGE:
        LOG.debug('abort re-draw')
        return

    if not data.seqdata:
        gtk_rgx.start_read(gui, run_after=[start_trim])
        return

    with iface.accept_rev.handler_block(iface.rev_handler):
        iface.accept_rev.set_active(iface.reverse_rx_chk.get_active())
        iface.accept_rev.set_sensitive(iface.reverse_rx_chk.get_active())

    LOG.debug('start-up redraw')
    data.qal_model.clear()
    sleep(.1)
    iface.thread = threading.Thread(target=do_trim, args=[gui])
    iface.running = True
    GObject.timeout_add(100, shared.update, iface, PAGE)
    iface.thread.start()
    # return to main loop


def do_trim(gui):
    """
    Iterate over records and trim, create a matrix representation
    of valid characters and plot as seaborn heatmap.
    :param gui:
    :return:
    """
    data, iface = gui.data, gui.iface
    # parameters are up-to-date
    LOG.debug('re-draw with %s' % str(iface.qal))
    p = iface.qal
    rows = list()
    data.gene_for_preview = p.gene_roll
    genes_for_preview = data.genes if p.gene_roll == 'all' else {p.gene_roll}
    ignore_ids = iface.qal.ignore_set if 'ignore_set' in iface.qal else set()
    iface.text = 'creating matrix'
    LOG.debug(iface.text)
    iface.i = 0
    iface.k = sum([len(data.seqdata[gene]) for gene in genes_for_preview]) + 3
    shared_ids = set.intersection(*data.gene_ids.values())

    try:
        for record_id, gene in data.record_order:
            # skip records from other genes for the trimming preview
            if gene not in genes_for_preview or record_id in ignore_ids:
                continue

            iface.i += 1
            # maybe skip reversed seqs
            if not p.accept_rev and data.metadata[gene][record_id]['is_rev']:
                continue

            record = data.seqdata[gene][record_id]
            try:
                record = trim_ends(record, p.min_phred, (p.trim_out, p.trim_of), trim_preview=True)
                record = mark_bad_stretches(record, p.min_phred, p.bad_stretch)
                has_qal, is_bad = True, False
                row = static.seqtoint(record)
            except AttributeError:
                # accept references anyway, but maybe skip no-phred ones
                is_ref = data.metadata[gene][record_id]['is_ref']
                if not is_ref and not p.accept_nophred:
                    continue
                has_qal, is_bad = is_ref, False
                row = static.seqtoint(record)
            except ValueError:
                has_qal, is_bad = True, True
                row = static.seqtogray(record)
            rows.append(row)
            underline = not has_qal if record.id in shared_ids else 4
            data.qal_model.append([record.id, underline, is_bad])

    except KeyError as ke:
        exit(ke)

    if not rows:
        LOG.warning('no sequence data remains')
        sleep(.1)
        GObject.idle_add(stop_trim, gui)
        return True

    # else: # todo sigsev?
    iface.text = 'tabularize'
    LOG.debug(iface.text)
    max_len = max(map(len, rows))
    array = np.array([row + static.seqtoint(' ') * (max_len - len(row)) for row in rows])
    # make gaps transparent
    array = np.ma.masked_where(array > static.toint('else'), array)
    iface.i += 1
    iface.text = 'plot'
    LOG.debug(iface.text)

    # adjust maximum size
    scale = 6
    while max(array.shape) * scale > 2 ** 14:
        scale -= 1
    LOG.debug('scaling qal with %d' % scale)

    f = Figure()
    f.set_facecolor('none')
    f.set_figheight(array.shape[0] / static.DPI)
    f.set_figwidth(array.shape[1] / static.DPI)
    ax = f.add_subplot(111)
    ax.axis('off')
    f.subplots_adjust(left=0, bottom=0, right=1, top=1, wspace=0, hspace=0)
    mat = ax.matshow(array, alpha=1, cmap=ListedColormap(static.colors),
                     vmin=-.5, vmax=len(static.colors) - .5, aspect='auto')

    iface.i += 1
    iface.text = 'save PNG'
    LOG.debug(iface.text)
    Path.mkdir(gui.wd / PATHS.preview.parent, exist_ok=True)
    f.savefig(gui.wd / PATHS.preview, transparent=True,
              dpi=scale * static.DPI, bbox_inches='tight', pad_inches=0.00001)

    data.qal_shape[0] = array.shape[1]
    data.qal_shape[1] = shared.get_height_resize(iface.view_qal, None, iface.qal_spacer, [iface.qal_win])

    if iface.rasterize.props.active:
        iface.text = 'place PNG'
        LOG.debug(iface.text)
        shared.load_image(iface.zoom, PAGE, iface.qal_eventbox, gui.wd / PATHS.preview,
                          data.qal_shape[0] * shared.get_hadj(iface), data.qal_shape[1])
    else:
        iface.text = 'place vector'
        LOG.debug(iface.text)
        canvas = FigureCanvas(f)  # a Gtk.DrawingArea
        # canvas.mpl_connect('pick_event', onpick)
        # canvas.mpl_connect('button_press_event', onclick)
        canvas.set_size_request(data.qal_shape[0] * shared.get_hadj(iface), data.qal_shape[1])
        try:
            iface.qal_eventbox.get_child().destroy()
            iface.qal_eventbox.add(canvas)
            # iface.qal_tools.attach(NavigationToolbar(canvas, gui.win), 1, 1, 1, 1)
        except Gtk.Error as ex:
            LOG.error(ex)
    iface.i += 1

    with plt.rc_context({'axes.edgecolor': iface.FG, 'xtick.color': iface.FG}):
        iface.text = 'colorbar'
        LOG.debug(iface.text)
        fig = plt.figure(figsize=(4, 2))
        cax = fig.add_subplot(111)
        cbar = plt.colorbar(mat, ax=cax, ticks=range(len(static.colors)), orientation='horizontal')
        cbar.ax.set_xticklabels(static.NUCLEOTIDES)
        cax.remove()
        fig.savefig(gui.wd / PATHS.cbar, transparent=True,
                    bbox_inches='tight', pad_inches=0, dpi=600)
        del fig
    shared.load_colorbar(iface.palplot, gui.wd)

    iface.text = 'idle'
    iface.frac = 1
    sleep(.1)
    GObject.idle_add(stop_trim, gui)
    return True


def stop_trim(gui):
    iface = gui.iface
    iface.running = False
    iface.thread.join()
    gui.win.show_all()
    iface.prog_bar.set_text('idle')
    LOG.info('qal thread idle')
    return False


def delete_event(widget, event):
    return False


def keypress(widget, event, data, iface):
    key = Gdk.keyval_name(event.keyval)
    if key == 'Up':
        widget.set_text(str(1 + int(widget.get_text())))
        return True
    elif key == 'Down':
        widget.set_text(str(max(0, -1 + int(widget.get_text()))))
        return True


def edit(widget, data, iface):
    """
    Edit a parameter entry and save the result
    """
    LOG.debug('editing')
    # filter for numbers only
    value = ''.join([c for c in widget.get_text() if c.isdigit()])
    widget.set_text(value if value else '')  # entering 0 is annoying


def trim_all(gui, run_after=None):
    """
    Trim all SeqRecords in project_dataset.seqdata to sequence strings and write collated .fasta files.
    Deleting SeqRecords will make the project file tiny again. If necessary, re-read trace files.
    Also place the png preview in the trim preview window.
    :param gui:
    :param run_after: the function to run after finishing. usually flip to next page.
    :return:
    """
    data, iface = gui.data, gui.iface

    if not data.seqdata:
        LOG.debug('re-reading files')
        gtk_rgx.start_read(gui, run_after=[trim_all])
        return

    p = iface.qal
    LOG.debug('writing collated .fasta files')
    shared_ids = set.intersection(*data.gene_ids.values())
    for gene, genedata in data.seqdata.items():
        Path.mkdir(gui.wd / gene, exist_ok=True)

        # do actual trimming
        for _id in data.gene_ids[gene]:
            record = genedata.pop(_id)
            try:
                record = trim_ends(record, p.min_phred, (p.trim_out, p.trim_of))
                record = mark_bad_stretches(record, p.min_phred, p.bad_stretch)
            except ValueError:
                continue
            except AttributeError:
                pass
            # put back only the good records
            genedata[_id] = record

        # write to file
        with open(str(gui.wd / gene / (gene + '_all.fasta')), 'w') as fasta:
            SeqIO.write(genedata.values(), fasta, 'fasta')
        # write only shared records to fasta for MSA
        with open(str(gui.wd / gene / (gene + '.fasta')), 'w') as fasta:
            SeqIO.write([record for _id, record in genedata.items()
                         if _id in shared_ids], fasta, 'fasta')

    LOG.debug('deleting seqdata')
    # delete now bloaty data
    data.seqdata.clear()

    shared.set_changed(gui, PAGE, False)
    if run_after:
        [run(gui) for run in run_after]
    return


def onpick(event):
    thisline = event.artist
    xdata = thisline.get_xdata()
    ydata = thisline.get_ydata()
    ind = event.ind
    points = tuple(zip(xdata[ind], ydata[ind]))
    print('onpick points:', points)
    print('This would be useful after the next big restructuring')
    return True


def onclick(event):
    print('%s click: button=%d, x=%d, y=%d, xdata=%f, ydata=%f' %
          ('double' if event.dblclick else 'single', event.button,
           event.x, event.y, event.xdata, event.ydata))
    print('This would be useful after the next big restructuring')
    return True
