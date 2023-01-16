import csv
import sys
import json
import asyncio
import contextlib

import synapse.exc as s_exc
import synapse.cortex as s_cortex
import synapse.common as s_common
import synapse.telepath as s_telepath

import synapse.lib.cmd as s_cmd
import synapse.lib.base as s_base
import synapse.lib.cmdr as s_cmdr
import synapse.lib.output as s_output
import synapse.lib.version as s_version

reqver = '>=0.2.0,<3.0.0'


async def runJsonImport(opts, outp, text, stormopts):

    def iterrows():
        for path in opts.jsonfiles:

            with open(path, 'r', encoding='utf8') as fd:

                def genr():

                    for row in fd:
                        yield row

                for rows in s_common.chunks(genr(), 1000):
                    yield rows

    rowgenr = iterrows()

    logfd = None
    if opts.logfile is not None:
        logfd = s_common.genfile(opts.logfile)
        logfd.seek(0, 2)

    async def addJsonData(core):

        nodecount = 0

        stormopts['editformat'] = 'splices'
        vars = stormopts.setdefault('vars', {})

        for rows in rowgenr:

            vars['rows'] = rows

            async for mesg in core.storm(text, opts=stormopts):

                if mesg[0] == 'node':
                    nodecount += 1

                elif mesg[0] == 'err' and not opts.debug:
                    outp.printf(repr(mesg))

                elif mesg[0] == 'print':
                    outp.printf(mesg[1].get('mesg'))

                if opts.debug:
                    outp.printf(repr(mesg))

                if logfd is not None:
                    byts = json.dumps(mesg).encode('utf8')
                    logfd.write(byts + b'\n')

        if opts.cli:
            await s_cmdr.runItemCmdr(core, outp, True)

        return nodecount

    if opts.test:
        async with s_cortex.getTempCortex() as core:
            nodecount = await addJsonData(core)

    else:
        async with await s_telepath.openurl(opts.cortex) as core:

            try:
                s_version.reqVersion(core._getSynVers(), reqver)
            except s_exc.BadVersion as e:
                valu = s_version.fmtVersion(*e.get('valu'))
                outp.printf(f'Cortex version {valu} is outside of the jsontool supported range ({reqver}).')
                outp.printf(f'Please use a version of Synapse which supports {valu}; '
                            f'current version is {s_version.verstring}.')
                return 1

            nodecount = await addJsonData(core)

    if logfd is not None:
        logfd.close()

    outp.printf('%d nodes.' % (nodecount, ))
    return 0

async def main(argv, outp=s_output.stdout):
    pars = makeargparser(outp)

    try:
        opts = pars.parse_args(argv)
    except s_exc.ParserExit as e:
        return e.get('status')

    with open(opts.stormfile, 'r', encoding='utf8') as fd:
        text = fd.read()

    stormopts = {}
    if opts.optsfile:
        stormopts = s_common.yamlload(opts.optsfile)

    if opts.view:
        if not s_common.isguid(opts.view):
            outp.printf(f'View is not a guid {opts.view}')
            return -1
        stormopts['view'] = opts.view

    async with s_telepath.withTeleEnv():

        return await runJsonImport(opts, outp, text, stormopts)

def makeargparser(outp):
    desc = '''
    Command line tool for ingesting json files into a cortex

    The storm file is run with the json rows specified in the variable "rows" so most
    storm files will use a variable based for loop to create edit nodes.  For example:

    for ($fqdn, $ipv4, $tag) in $rows {

        [ inet:dns:a=($fqdn, $ipv4) +#$tag ]

    }

    More advanced uses may include switch cases to provide different logic based on
    a column value.

    for $i in $rows {
        $json = $lib.json.load($i)
        switch $json.type {

            fqdn: {
                [ inet:fqdn=$valu ]
            }

            "person name": {
                [ ps:name=$valu ]
            }

            *: {
                // default case...
            }

        }

        switch $json.info {
            "known malware": { [+#cno.mal] }
        }

    }
    '''
    pars = s_cmd.Parser('synapse.tools.jsontool', description=desc, outp=outp)
    pars.add_argument('--logfile', help='Set a log file to get JSON lines from the server events.')
    pars.add_argument('--cli', default=False, action='store_true',
                      help='Drop into a cli session after loading data.')
    pars.add_argument('--debug', default=False, action='store_true', help='Enable verbose debug output.')
    muxp = pars.add_mutually_exclusive_group(required=True)
    muxp.add_argument('--cortex', '-c', type=str,
                      help='The telepath URL for the cortex ( or alias from ~/.syn/aliases ).')
    muxp.add_argument('--test', '-t', default=False, action='store_true',
                      help='Perform a local json ingest against a temporary cortex.')
    pars.add_argument('--view', default=None, action='store',
                      help='Optional view to work in.')
    pars.add_argument('--optsfile', default=None, action='store',
                      help='Path to an opts file (.yaml) on disk.')
    pars.add_argument('stormfile', help='A Storm script describing how to create nodes from rows.')
    pars.add_argument('jsonfiles', nargs='+', help='json files to load.')
    return pars

if __name__ == '__main__':  # pragma: no cover
    sys.exit(asyncio.run(s_base.main(main(sys.argv[1:]))))

