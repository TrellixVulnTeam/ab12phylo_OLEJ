# 2021 Leo Kaindl

import configparser
import logging
import random
import shlex
import shutil
import stat
import sys
import threading
from os import cpu_count
from pathlib import Path
from subprocess import call, run, Popen, PIPE
from time import sleep, time
from zipfile import ZipFile, ZIP_DEFLATED

import gi
import requests

gi.require_version('Gtk', '3.0')
from gi.repository import Gtk, GObject

from ab12phylo import repo
from ab12phylo.gtk_base import ab12phylo_app_base

LOG = logging.getLogger(__name__)
PAGE = 6


class ml_page(ab12phylo_app_base):

    def __init__(self):
        super().__init__()
        data = self.data
        iface = self.iface

        iface.ml_tool.set_entry_text_column(0)
        iface.ml_tool.set_id_column(0)
        iface.ml_tool.connect('changed', self._load_ml_help)
        iface.ml_exe.connect('file-set', self._load_ml_help, True)
        iface.ml_cmd.connect('focus_in_event', lambda widget, *args: self.start_ML(widget, 'prep'))

        iface.evo_model.set_model(data.evo_models)
        iface.evo_model.get_child().connect(
            'focus_out_event', self._change_evo_model, iface.evo_modify, data.ml)
        iface.evo_block = iface.evo_model.connect_after(
            'changed', self._load_model_file, iface.evo_modify)
        iface.evo_model.handler_block(iface.evo_block)

        iface.ml_run.connect('clicked', self.start_ML, '')
        iface.ml_export.connect('clicked', self.start_ML, '_export')
        iface.ml_import.connect('clicked', self.import_tree)  # TODO also

        for wi in [iface.bootstraps, iface.rand, iface.pars, iface.ml_seed]:
            wi.connect('key-press-event', self.edit_numerical_entry_up_down)
            wi.connect('changed', self.edit_numerical_entry)

        iface.raxml_seen = False

    def import_tree(self, widget):
        """Import a tree file or two"""
        dialog = Gtk.FileChooserDialog(title='import tree(s)',
                                       parent=None, select_multiple=True,
                                       action=Gtk.FileChooserAction.OPEN)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            paths = [Path(p).resolve() for p in dialog.get_filenames()]
            if len(paths) > 2:
                self.show_message_dialog('Please select at most two tree files.')
            else:
                errors = list()
                for path in paths:
                    if 'FBP' in path.name.upper():
                        shutil.copy(path, self.wd / repo.PATHS.fbp)
                    elif 'TBE' in path.name.upper():
                        shutil.copy(path, self.wd / repo.PATHS.tbe)
                    else:
                        errors.append(path.name)
                if errors:
                    self.show_message_dialog('Not immediately recognized as either '
                                             'tree_FBP.nwk or tree_TBE.nwk. You can also copy '
                                             'it/them to %s manually.' % self.wd, items=errors)
                else:
                    self.show_notification('imported trees:',
                                           [path.name for path in paths], 2)
                    self.set_errors(PAGE, False)

        dialog.destroy()
        self.set_changed(PAGE, False)

    @staticmethod
    def _change_evo_model(entry, event_focus, evo_modify, ml):
        combo = entry.get_parent().get_parent()
        if combo.get_active_iter():
            ml.evo_model = entry.get_text()
            evo_modify.props.sensitive = True
        else:
            tx = entry.get_text()
            combo.get_model().append([tx, None])
            ml.evo_model = tx  # save in project dataset
            LOG.debug('entered custom evo model %s' % tx)

    def _load_model_file(self, combo, evo_modify):
        if combo.get_active_iter() and combo.get_active_id() == 'from file':
            dialog = Gtk.FileChooserDialog(title='select file with partition table',
                                           parent=None, select_multiple=False,
                                           action=Gtk.FileChooserAction.OPEN)
            dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                               Gtk.STOCK_OPEN, Gtk.ResponseType.OK)
            response = dialog.run()
            if response == Gtk.ResponseType.OK:
                tx = Path(dialog.get_filename()).resolve()
                try:
                    Path.mkdir(self.wd / 'RAxML', exist_ok=True)
                    shutil.copy(tx, self.wd / 'RAxML' / 'user_model')
                    shutil.copy(tx, self.wd / 'RAxML' / 'ml.raxml.bestModel')
                except FileNotFoundError:
                    self.show_notification('File does not exist', secs=1)
                    dialog.destroy()
                    return
                except shutil.SameFileError:
                    pass
                evo_modify.props.sensitive = False
                combo.get_model().append([tx.name, str(tx)])
                combo.set_active_id(tx.name)
                LOG.debug('selected partitioned model file: %s -> RAxML/user_model' % str(tx))
            dialog.destroy()

    def _load_ml_help(self, widget, try_path=False):
        """
        Load the RAxML-NG / IQ-Tree path from the config file or use the user-defined one.
        If --help exits with OSError, despair.
        """
        iface = self.iface
        ml = self.data.ml
        tool = repo.toalgo(iface.ml_tool.get_active_text())
        for wi in [iface.iqtree_label, iface.ultrafast, iface.infer_model]:
            wi.set_sensitive(tool != 'raxml-ng')

        if try_path:
            binary = widget.get_filename()
        else:
            # fetch the path from the config
            cfg_parser = configparser.ConfigParser()
            cfg_parser.read(ab12phylo_app_base.CONF)
            binary = cfg_parser['Paths'].get(tool, shutil.which(tool))

        if binary:
            # May be missing, for example no RAxML-NG on Windows
            ml.binary = binary
            iface.ml_exe.set_filename(binary)
            binary = Path(binary)
            # Ensure the file is executable
            binary.chmod(binary.stat().st_mode | stat.S_IEXEC)

            try:
                res = run(args=shlex.split(f'{ml.binary} --help'),
                          stdout=PIPE, stderr=PIPE)
                iface.ml_help.props.buffer.props.text = res.stdout.decode().lstrip()
                LOG.debug('got %s --help' % tool)
            except OSError:
                if sys.platform in ['win32', 'darwin', 'cygwin']:
                    self.show_notification('The selected binary doesn\'t work for this OS.\n'
                                           'Please use a different tool or export a .zip\n'
                                           'and run ML inference on a different machine.\n'
                                           + ml.binary)
                else:
                    assert sys.platform == 'linux', 'What\'s AIX?'

        try:
            # get number of available CPUs
            cpus = cpu_count()
            iface.cpu_count.set_text(str(cpus))
            cpu_adj = iface.cpu_use.get_adjustment().props
            cpu_adj.upper = cpus
            cpu_adj.value = cpus
            LOG.debug('found %d CPUs' % cpus)
        except Exception as ex:
            LOG.error('reading CPUs failed')

    @staticmethod
    def _prep_calls(ml):
        # prepare the calls
        chck = '"%s" --msa "%s" --check --model "%s' \
               + ml.evo_modify + '" --prefix "%s"'

        inML = '"%s" --msa "%s" --model "%s' + ml.evo_modify + \
               '" --prefix "%s"' + ' --seed %d' % ml.ml_seed + \
               ' --threads auto{%s} --workers auto{%s}' + \
               ' --redo --tree %s ' % ','.join(
            [a for a in ['rand{%d}' % ml.rand if ml.rand > 0 else None,
                         'pars{%d}' % ml.pars if ml.pars > 0 else None] if a])

        boot = '"%s" --bootstrap --msa "%s" --model "%s" --tree "%s"' + \
               ' --prefix "%s"' + ' --bs-trees %d' % ml.bootstraps + \
               ' --seed %d' % ml.ml_seed + \
               ' --threads auto{%s} --workers auto{%s} --redo'

        supp = '"%s" --support --tree "%s" --bs-trees "%s" --bs-metric fbp,tbe ' + \
               '--prefix "%s" --threads ' + \
               'auto{%s} --workers auto{%s} --redo'

        # res = run(stdout=PIPE, stderr=PIPE, args=shlex.split(
        #     arg % (ml.binary, msa, prefix / 'bs_')))
        # res = run(stdout=PIPE, stderr=PIPE, shell=True,
        #           args=arg % (ml.binary, msa, prefix / 'bs_'))
        # notify = 'notify-send "AB12PHYLO" "ML Tree Inference finished!" -u normal -i "%s"' \
        #          % str(BASE_DIR / 'ab12phylo' / 'files' / 'favi.png')
        # notify2 = 'zenity --notification --text="AB12PHYLO\nML Tree Inference finished" ' \
        #           '--window-icon="%s"' % str(BASE_DIR / 'ab12phylo' / 'files' / 'favi.png')

        iqtree = 'bonk'  # TODO
        iq_args = '"%s" -s "%s" -pre "%s" -ninit %d -bb %d -nt AUTO -ntmax %s -seed %d' \
                  % (iqtree, 'msa', 'prefix', ml.pars, ml.bootstraps, ml.cpu_use, ml.ml_seed)
        iq_modeltest = '"%s" -m MF -pre "%s"'
        '-bb ultrafast -b non-parametric'

        return chck, inML, boot, supp, iq_args

    def reload_ui_state(self):
        data = self.data
        iface = self.iface
        ml = data.ml
        for w_name in ['bootstraps', 'rand', 'pars']:
            iface.__getattribute__(w_name).set_text(str(ml.__getattribute__(w_name)))
        iface.ml_seed.set_text(str(ml.ml_seed) if 'ml_seed' in ml else '')
        iface.evo_model.set_active_id(ml.evo_model)
        iface.evo_modify.set_text(ml.evo_modify)
        iface.in_shell.set_active(ml.in_shell)

    def refresh(self):
        """Re-view the page. Get suggested commands for RAxML-NG and IQ-Tree"""
        LOG.debug('ML refresh')
        data = self.data
        iface = self.iface
        if not iface.raxml_seen:
            self._load_ml_help(None)
            self.reload_ui_state()
            iface.evo_model.handler_unblock(iface.evo_block)
            iface.evo_model.set_active_id(data.ml.evo_model)
            iface.raxml_seen = True

        self.set_errors(PAGE, not any((self.wd / a).is_file()
                                      for a in [repo.PATHS.tbe, repo.PATHS.fbp]))
        # change the button to its default state
        (im, la), tx = iface.ml_run.get_child().get_children(), 'Run'
        im.set_from_icon_name('media-playback-start-symbolic', 4)
        la.set_text('Run')

    def start_ML(self, widget, mode, run_after=None):
        """Set-up the ML inference thread"""
        data = self.data
        iface = self.iface
        ml = data.ml

        if not data.genes:
            self.show_notification('No genes', secs=1)
            return
        elif iface.thread.is_alive():
            # The button was pressed when it was in the 'Stop' state
            iface.pill2kill.set()
            return

        ml.binary = iface.ml_exe.get_filename()
        for w_name in ['evo_modify', 'bootstraps', 'rand', 'pars', 'ml_seed', 'cpu_use']:
            wi = iface.__getattribute__(w_name)
            val = [i for i in [wi.get_text(), wi.get_placeholder_text()] if i][0]
            if w_name in ['bootstraps', 'rand', 'pars']:
                val = int(val)
            ml.__setattr__(w_name, val)
        ml.evo_model = data.evo_models[iface.evo_model.get_active()]
        if ml.evo_model[1]:
            ml.evo_modify = ''
            ml.evo_model = str(self.wd / 'RAxML' / 'user_model')
        else:
            ml.evo_model = ml.evo_model[0]

        ml.ml_seed = random.randint(0, max(1000, ml.bootstraps)) \
            if ml.ml_seed == 'random' else int(ml.ml_seed)
        iface.ml_seed.props.text = str(ml.ml_seed)
        Path.mkdir(self.wd / 'RAxML', exist_ok=True)
        ml.in_shell = iface.in_shell.get_active()

        tool = repo.toalgo(iface.ml_tool.get_active_text())
        if mode == 'prep':
            # update the cmd preview
            calls = self._prep_calls(ml)
            # TODO paste some more info in there..... oh no manual wildcard formatting
            if tool == 'raxml-ng':
                calls = calls[:4]
            else:
                calls = calls[4:]
            iface.ml_cmd.get_buffer().props.text = '\n'.join(calls)
            return

        # prepend the tool to the mode
        mode = tool + mode

        iface.run_after = run_after
        # to keep the progress bar up-to-date:
        ml.prev = 0
        ml.key = False
        ml.stdout = list()
        ml.seen = {'ML': set(), 'BS': set()}
        ml.motifs = {'ML': 'ML tree search #', 'BS': 'Bootstrap tree #'}
        iface.k = ml.bootstraps + ml.rand + ml.pars + 3 if mode in {'raxml-ng', 'iqtree2'} else 2
        self.save()
        sleep(.1)

        # change the button to its stop state
        (im, la), tx = iface.ml_run.get_child().get_children(), 'Run'
        im.set_from_icon_name('media-playback-stop-symbolic', 4)
        la.set_text('Stop')
        iface.tup = (im, la, tx)

        iface.thread = threading.Thread(target=self.do_ML, args=[mode])
        GObject.timeout_add(100, self.update_ML, PAGE, ml)
        iface.thread.start()
        return  # to main loop

    def do_ML(self, mode):
        """Run the ML inference thread"""
        data = self.data
        iface = self.iface
        ml = data.ml
        start = time()
        msa = self.wd / repo.PATHS.msa
        prefix = self.wd / 'RAxML'
        shell = self.wd / 'raxml_run.sh'
        errors = list()
        iface.i = 0

        chck, inML, boot, supp, iq_args = self._prep_calls(ml)

        if ml.in_shell:
            with open(shell, 'w') as sh:
                sh.write('#!/bin/bash\n\n')

        # loop over the stages
        for i, (desc, key, prev, arg, add) in enumerate(zip(
                ['check MSA', 'infer ML tree', 'bootstrapping', 'calc. branch support'],
                [False, 'ML', 'BS', False], [0, 1, ml.rand + ml.pars + 1, iface.k - 2],
                [chck, inML, boot, supp],
                [(ml.binary, msa, ml.evo_model, prefix / 'chk'),
                 (ml.binary, msa, ml.evo_model,
                  prefix / 'ml', ml.cpu_use, ml.cpu_use),
                 (ml.binary, msa, prefix / 'ml.raxml.bestModel',
                  prefix / 'ml.raxml.bestTree',
                  prefix / 'bs', ml.cpu_use, ml.cpu_use),
                 (ml.binary, prefix / 'ml.raxml.bestTree',
                  prefix / 'bs.raxml.bootstraps',
                  prefix / 'sp', ml.cpu_use, ml.cpu_use)])):

            if ml.in_shell and mode == 'raxml-ng':
                with open(shell, 'a') as sh:
                    sh.write('# %s\n' % desc)
                    # sh.write(arg % add)
                    if i != 2:
                        sh.write(arg % add)
                    else:
                        # special case bootstrapping:
                        fifo = Path('pipe')
                        if fifo.exists():
                            fifo.unlink()
                        bash = '''
mkfifo pipe || exit 1
(%s) > pipe &
pid=$!
echo "AB12PHYLO: Bootstrapping PID is $pid"
while read -r line; do
    echo "$line"
    if [[ "${line::12}" == "Elapsed time" ]]; then
        echo "AB12PHYLO: Finished bootstrapping, terminating process $pid to ensure it exits."
        kill -s SIGTERM $pid
        break
    fi
done < pipe
rm pipe
                        '''.strip() % (arg % add)
                        sh.write(bash)
                    sh.write('\n\necho "AB12PHYLO: %s done"\n' % desc)
                    if i != 3:
                        sh.write('\nsleep 1s\n\n')
                    continue

            # running RAxML, but live rather than in shell mode
            iface.text = desc
            LOG.info(iface.text)
            ml.stdout = list()
            ml.key = key
            ml.prev = prev

            # read realtime RAxML output line by line
            proc = Popen(args=shlex.split(arg % add), stdout=PIPE, stderr=PIPE)
            while True and not iface.pill2kill.is_set():
                line = proc.stdout.readline()
                if proc.poll() is not None:
                    sleep(.2)
                    break
                if line:
                    lane = line.decode().rstrip()
                    ml.stdout.append(lane)
                    LOG.debug(lane)
                    if lane.startswith('Elapsed time'):
                        break
                else:
                    sleep(.2)
                    break

            if iface.pill2kill.is_set():
                sleep(.2)
                GObject.idle_add(self.stop_ML, errors, start)
                return True

            # bf = iface.ml_help.get_buffer()
            # bf.props.text = bf.props.text + '\n' + '\n'.join(ml.stdout)
            # bf.insert_markup(bf.get_end_iter(),
            #                  '<span foreground="#2374AF">'
            #                  '________________________________________________'
            #                  '________________________________\n</span>', -1)
            # mark = bf.create_mark(None, bf.get_end_iter(), True)
            # iface.ml_help.scroll_mark_onscreen(mark)
            # bf.add_mark(Gtk.TextMark.new(stage, True), bf.get_end_iter())
            # iface.ml_help.scroll_to_iter(bf.get_end_iter(), .1, False, 0, .9)

            # check for errors
            for line in ml.stdout:
                if line.startswith('ERROR'):
                    errors.append(line)
            if errors:
                GObject.idle_add(self.stop_ML, errors, start)
                return True

            if mode == 'raxml-ng_export':
                iface.text = 'building zip'
                LOG.debug(iface.text)
                sh = 'raxml_run.sh'
                with open(sh, 'w', newline='') as sf:
                    bash = '''
#!/bin/bash\n
# Execute this script via 'bash raxml_run.sh'\n
# get the number of CPUs available
cpus=$(nproc)\n
BLUE='\033[0;34m'
NC='\033[0m' # No Color
print_usage() {
  printf "Limit the number of threads/logical cores via ${BLUE}-f <number>${NC}. "\n}\n
cpu_limit=400\n
while getopts 'f:' flag; do
  case "${flag}" in
    f) cpu_limit="${OPTARG}" ;;
    *) print_usage
       exit 1 ;;\n  esac\ndone\n
# find the minimum of the CPUs allowed and available
if [ $cpu_limit -lt $cpus ]; then
    used=$cpu_limit\nfi
if [ $cpus -lt $cpu_limit ];then
    used=$cpus\nfi\n
printf "${BLUE}$cpus${NC} CPUs available, use at most ${BLUE}$used${NC}.\nThis will proceed in a bit, interrupt with Ctrl+C\n"
print_usage
# make binary executable
chmod +x "raxml-ng"
sleep 10s
                    '''.strip()
                    sf.write(bash)
                    sf.write('\n\n# Check MSA\n')
                    sf.write(chck % ('./raxml-ng', 'msa.fasta',
                                     Path(ml.evo_model).name, 'chk'))
                    sf.write('\n\n# Find best ML tree\n')
                    sf.write(inML % ('./raxml-ng', 'msa.fasta',
                                     Path(ml.evo_model).name, 'ml', '$used', '$used'))
                    sf.write('\n\n# Compute bootstrap iterations\n')
                    sf.write(boot % ('./raxml-ng', 'msa.fasta', 'ml.raxml.bestModel',
                                     'ml.raxml.bestTree', 'bs', '$used', '$used'))
                    sf.write('\n\n# Calculate branch support\n')
                    sf.write(supp % ('./raxml-ng', 'ml.raxml.bestTree',
                                     'bs.raxml.bootstraps', 'sp', '$used', '$used'))
                    sf.write('\n\n# Copy tree files\n')
                    sf.write('cp sp.raxml.supportTBE tree_TBE.nwk')
                    sf.write('cp sp.raxml.supportFBP tree_FBP.nwk')
                    sf.write('\n\n')

                sleep(.05)
                GObject.idle_add(self.export_zip, sh, msa)
                return True

        if ml.in_shell and mode == 'raxml-ng':
            shell.chmod(shell.stat().st_mode | stat.S_IEXEC)
            self.hold()
            self.win.hide()
            sleep(.1)
            Popen(['notify-send', 'AB12PHYLO', 'ML Tree Inference running in background.',
                   '-i', str(repo.PATHS.icon_path)])
            call([shell])
            sleep(.1)
            self.win.show_all()
            self.release()

        iface.text = 'copy tree files'
        iface.i = iface.k - 1
        shutil.copy(prefix / 'sp.raxml.supportFBP', self.wd / repo.PATHS.fbp)
        shutil.copy(prefix / 'sp.raxml.supportTBE', self.wd / repo.PATHS.tbe)
        iface.text = 'idle'
        iface.frac = 1
        sleep(.1)
        GObject.idle_add(self.stop_ML, errors, start)
        return True

    def stop_ML(self, errors, start):
        """Finish the ML inference thread"""
        iface = self.iface
        iface.thread.join()
        self.update_ML(PAGE, self.data.ml)
        self.win.show_all()

        # change the button to its stop state
        im, la, tx = iface.tup
        im.set_from_icon_name('media-playback-start-symbolic', 4)
        la.set_text(tx)
        if errors:
            self.show_notification('Errors during ML inference', errors)
        elif iface.pill2kill.is_set():
            tx = 'stopped ML inference'
            self.show_notification(msg=tx, secs=2)
        elif time() - start > 120:
            Popen(['notify-send', 'AB12PHYLO', 'ML Tree Inference finished',
                   '-i', str(repo.PATHS.icon_path)])
            # notify = threading.Thread(target=_zenity, args=())
            # notify.start()
        else:
            tx = 'ML inference finished'
            self.show_notification(tx)
        LOG.info(tx)
        iface.pill2kill.clear()
        self.refresh()
        if iface.run_after:
            [do_func() for do_func in iface.run_after]
        self.set_changed(PAGE, False)
        return

    def export_zip(self, sh, msa):
        """Finish the zip export thread"""
        data = self.data
        iface = self.iface
        ml = data.ml
        iface.thread.join()
        self.win.show_all()

        path = self.wd / 'RAxML_export.zip'
        dialog = Gtk.FileChooserDialog(title='export zip',
                                       parent=None, select_multiple=False,
                                       action=Gtk.FileChooserAction.SAVE)
        dialog.add_buttons(Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL,
                           Gtk.STOCK_SAVE, Gtk.ResponseType.OK)
        dialog.set_do_overwrite_confirmation(True)
        dialog.set_current_folder(str(path.parent))
        dialog.set_current_name(path.name)
        response = dialog.run()
        if response == Gtk.ResponseType.OK:
            try:
                p = Path(dialog.get_filename()).resolve()
                with ZipFile(p, 'w', ZIP_DEFLATED) as zf:
                    if ml.evo_model.endswith('user_model'):
                        zf.write(ml.evo_model, 'user_model')
                    zf.write(ml.binary, 'raxml-ng')
                    zf.write(msa, 'msa.fasta')
                    zf.write(sh)
                Path(sh).unlink()
            except Exception as ex:
                LOG.error(ex)
        dialog.destroy()

        # change the button to its stop state
        im, la, tx = iface.tup
        im.set_from_icon_name('media-playback-start-symbolic', 4)
        la.set_text(tx)
