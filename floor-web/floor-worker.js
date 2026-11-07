// floor-worker.js - the Helix Floor build (helix-floor/floor/build_floor2.py) in the browser.
// Pyodide runs the repository's own Python stages on the user's stock Helix Floor 3.80.0 file,
// without the simulator check (minutes here), then compares the result's MD5 with the build that
// was tested on a Helix Floor: a match means these are exactly those bytes.
//
// In:  { stock: ArrayBuffer }
// Out: { type: "progress", step, of, text } | { type: "log", text }
//      { type: "done", file, bytes: ArrayBuffer, md5, pinned } | { type: "error", text }
"use strict";

var PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/";
var STOCK_MD5 = "805caa03e8a30fd6ff7892f32ed5a9f4";   // Helix_Floor_v3.80.0_0x7d01f5efb.hxf
var BUILT_MD5 = "f4338695c5fa965f9100a0d82e632b7e";   // NAM2 (NOMASK kernel, DSP cost 3600), tested on a unit
var OUT_NAME = "Helix_Floor_v3.80.0_NAM2.hxf";

// What the build reads, relative to the repository root (the page sits in floor-web/).
var SOURCES = [
  "helix-floor/floor/upstream.py",
  "helix-floor/floor/arm_guards.py",
  "helix-floor/floor/ir_title.py",
  "helix-floor/floor/floor_hxf.py",
  "helix-floor/floor/nam_floor.py",
  "helix-floor/floor/nam_floor2.py",
  "helix-floor/floor/nam_floor3.py",
  "helix-floor/floor/nam_floor5.py",
  "helix-floor/floor/stage_slots.py",
  "helix-floor/floor/stage_slots2.py",
  "helix-floor/floor/stage_model.py",
  "helix-floor/floor/stage_kernel.py",
  "helix-floor/floor/stage_main.py",
  "helix-floor/floor/build_floor.py",
  "helix-floor/floor/build_staged.py",
  "helix-floor/floor/build_test2b.py",
  "helix-floor/floor/build_test2c.py",
  "tools/hxf.py",
  "tools/l6ia.py",
  "tools/l6ia_verify.py",
  "tools/patch_amp.py",
  "tools/sharc/entry4_blob.py",
  "tools/sharc/nam_lite.py",
  "tools/sharc/nam_multi.py",
  "tools/sharc/nam_multi_kernel.asm",
  "tools/sharc/nam_pack.py",
  "tools/sharc/sasm.py",
  "tools/sharc/ssim.py",
];

var DRIVER = [
  "import contextlib, hashlib, io, os, runpy, sys",
  "os.chdir('/repo')",
  "sys.modules['capstone'] = None          # (listing only; not in Pyodide)",
  "os.environ.update(NAM_KERNEL='nam_floor5', NAM_MAX_BLOCKS='16', NAM_DIAG='1')   # NAM_DIAG: no simulator check",
  "def run(argv):",
  "    out = io.StringIO()",
  "    sys.argv = list(argv)",
  "    try:",
  "        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):",
  "            runpy.run_path(argv[0], run_name='__main__')",
  "    except SystemExit as e:",
  "        if e.code not in (None, 0):",
  "            raise RuntimeError(out.getvalue() + str(e.code))",
  "    return out.getvalue()",
  "def md5(path):",
  "    return hashlib.md5(open(path, 'rb').read()).hexdigest()",
].join("\n");

var py = null;

function post(m, t) { self.postMessage(m, t || []); }
function progress(step, of, text) { post({ type: "progress", step: step, of: of, text: text }); }

async function boot() {
  importScripts(PYODIDE + "pyodide.js");
  py = await loadPyodide({ indexURL: PYODIDE });
  await py.loadPackage("numpy");
  for (var i = 0; i < SOURCES.length; i++) {
    var rel = SOURCES[i];
    var r = await fetch("../" + rel);
    if (!r.ok) throw new Error("Could not load " + rel + " (" + r.status + ")");
    var data = new Uint8Array(await r.arrayBuffer());
    var dir = "/repo/" + rel.split("/").slice(0, -1).join("/");
    py.FS.mkdirTree(dir);
    py.FS.writeFile("/repo/" + rel, data);
  }
  py.runPython(DRIVER);
}

async function build(stock) {
  var OF = 8;
  progress(1, OF, "Loading Python and the build tools (first time: about a minute)");
  if (!py) await boot();
  var run = py.globals.get("run");
  var md5 = py.globals.get("md5");
  py.FS.mkdirTree("/work");
  py.FS.writeFile("/work/stock.hxf", new Uint8Array(stock));
  progress(2, OF, "Checking your stock file");
  var got = md5("/work/stock.hxf");
  if (got !== STOCK_MD5) {
    throw new Error("This is not Line 6's Helix Floor 3.80.0 file (" + got + "). You need " +
      "Helix_Floor_v3.80.0_0x7d01f5efb.hxf, unchanged.");
  }
  var s = ["/work/s0.l6ia", "/work/s1.l6ia", "/work/s2.l6ia", "/work/s3.l6ia", "/work/s4.l6ia"];
  var F = "helix-floor/floor/";
  var steps = [
    ["Unpacking", ["tools/hxf.py", "unpack", "/work/stock.hxf", s[0]]],
    ["Making room in the DSP memory", [F + "stage_slots2.py", s[0], s[1]]],
    ["Adding the NAM A2 Lite model", [F + "stage_model.py", s[1], s[2]]],
    ["Assembling the NAM kernel", [F + "stage_kernel.py", s[2], s[3]]],
    ["Patching the main program", [F + "stage_main.py", s[3], s[4]]],
  ];
  for (var i = 0; i < steps.length; i++) {
    progress(3 + i, OF, steps[i][0]);
    post({ type: "log", text: run(py.toPy(steps[i][1])) });
    if (i > 0) try { py.FS.unlink(s[i - 1]); } catch (e) { /* (memory) */ }
  }
  var v = run(py.toPy(["tools/l6ia_verify.py", s[4]]));
  if (v.indexOf("ALL OK") < 0) throw new Error("The firmware check failed:\n" + v);
  progress(8, OF, "Packing the firmware file");
  run(py.toPy([F + "floor_hxf.py", "pack", s[4], "/work/out.hxf", "--donor", "/work/stock.hxf"]));
  var out = md5("/work/out.hxf");
  var bytes = py.FS.readFile("/work/out.hxf");
  ["/work/out.hxf", s[4], "/work/stock.hxf"].forEach(function (p) { try { py.FS.unlink(p); } catch (e) { } });
  var buf = bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength);
  post({ type: "done", file: OUT_NAME, bytes: buf, md5: out, pinned: out === BUILT_MD5 }, [buf]);
}

self.onmessage = function (ev) {
  build(ev.data.stock).catch(function (err) { post({ type: "error", text: String(err && err.message || err) }); });
};
