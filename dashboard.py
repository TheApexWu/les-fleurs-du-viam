"""Browser dashboard for driving the arm: wrist camera, pose, gripper, jog controls, STOP, log.

  python dashboard.py         then open http://localhost:8765

Same Jogger as teleop.py, so the limits, the log and the one-move-at-a-time rule are identical.
Listens on localhost only: the page can move a real arm, so it is not exposed to the network.
"""
import asyncio
import json

from aiohttp import web

import config as K
from teleop import STEPS_MM, Jogger

PORT = 8765


async def build_app():
    from viam.components.arm import Arm
    from viam.components.camera import Camera
    from flowers import connect

    robot = await connect()
    jog = Jogger(Arm.from_robot(robot, K.ARM))
    cam = Camera.from_robot(robot, K.CAMERA)
    await jog.start()
    lines: list[str] = []

    async def index(_):
        return web.Response(text=PAGE, content_type="text/html")

    async def frame(_):
        imgs, _ = await cam.get_images(filter_source_names=["color"])
        return web.Response(body=imgs[0].data, content_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def state(_):
        if jog.latest is None:
            return web.json_response({"waiting": True}, status=503)
        pose, joints, g = jog.latest["pose"], jog.latest["joints"], jog.latest["gripper"]
        return web.json_response({"pose": pose, "joints": joints, "gripper": g, "busy": jog.busy.locked(),
                                  "step_mm": STEPS_MM[jog.step_i], "last": jog.last, "lines": lines[-12:],
                                  "log": f"{jog.log_path.name} + {jog.trace_path.name}"})

    async def key(req):
        body = await req.json()
        msg = await jog.handle(body.get("key", ""), body.get("label", ""))
        lines.append(msg)
        return web.json_response({"msg": msg})

    async def stop(_):
        msg = await jog.stop()
        lines.append(msg)
        return web.json_response({"msg": msg})

    async def cleanup(_):
        await jog.arm.stop()
        jog.close()
        await robot.close()

    app = web.Application()
    app.add_routes([web.get("/", index), web.get("/frame.jpg", frame), web.get("/state", state),
                    web.post("/key", key), web.post("/stop", stop)])
    app.on_cleanup.append(cleanup)
    return app


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Les Fleurs du Viam - Teleop</title>
<style>
:root{--bg:#111;--fg:#eee;--mut:#999;--acc:#3a7;--bad:#d33;--card:#1c1c1c}
body{margin:0;background:var(--bg);color:var(--fg);font:14px -apple-system,Helvetica,sans-serif}
.wrap{display:grid;grid-template-columns:minmax(320px,640px) 1fr;gap:16px;padding:16px}
@media(max-width:900px){.wrap{grid-template-columns:1fr}}
.card{background:var(--card);border-radius:8px;padding:12px}
img{width:100%;border-radius:6px;display:block;transition:transform .2s}
h1{font-size:16px;margin:0 0 8px} .mut{color:var(--mut)}
table{border-collapse:collapse;width:100%} td{padding:3px 6px;border-bottom:1px solid #2a2a2a;font-variant-numeric:tabular-nums}
.grid{display:grid;grid-template-columns:repeat(3,64px);gap:6px;margin:8px 0}
button{background:#2a2a2a;color:var(--fg);border:1px solid #3a3a3a;border-radius:6px;padding:10px 0;font-size:14px;cursor:pointer}
button:hover{border-color:var(--acc)} button.on{border-color:var(--acc);color:var(--acc)}
#stop{background:var(--bad);border:0;font-size:22px;font-weight:700;width:100%;padding:18px 0;margin:8px 0}
#busy{display:inline-block;width:10px;height:10px;border-radius:5px;background:#444;margin-left:6px}
#busy.b{background:#e90}
#lines{font:12px Menlo,monospace;white-space:pre-wrap;max-height:220px;overflow:auto}
.warn{color:#e90}
</style></head><body><div class="wrap">
<div class="card"><h1>Wrist camera <span class="mut">(R rotates view)</span></h1><img id="cam" src="/frame.jpg"></div>
<div>
 <button id="stop" onclick="stop()">STOP (space)</button>
 <div class="card"><h1>State <span id="busy"></span></h1><table id="st"></table></div>
 <div class="card" style="margin-top:12px"><h1>Jog <span class="mut" id="step"></span></h1>
  <div class="grid">
   <button onclick="k('q')">Q spin-</button><button onclick="k('w')">W x+</button><button onclick="k('e')">E spin+</button>
   <button onclick="k('a')">A y+</button><button onclick="k('s')">S x-</button><button onclick="k('d')">D y-</button>
   <button onclick="k('r')">R z+</button><button onclick="k('\\t')">Tab step</button><button onclick="k('f')">F z-</button>
   <button onclick="k('o')">O open</button><button onclick="k('g')">G gentle</button><button onclick="k('c')">C close</button>
  </div>
  <button onclick="mark()" style="width:100%">M mark this moment</button>
  <p class="mut">Keyboard works when this page has focus. Keys are ignored while a move runs.
  View rotation: <button id="rot" onclick="rot()">0&deg;</button></p></div>
 <div class="card" style="margin-top:12px"><h1>Log <span class="mut" id="logname"></span></h1><div id="lines"></div></div>
</div></div>
<script>
let angle=0;
const post=(u,b)=>fetch(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(b||{})}).then(r=>r.json());
function stop(){post('/stop')}
function k(key,label){return post('/key',{key,label})}
function mark(){const l=prompt('label for this moment');if(l)k('m',l)}
function rot(){angle=(angle+90)%360;document.getElementById('cam').style.transform=`rotate(${angle}deg)`;document.getElementById('rot').innerHTML=angle+'&deg;'}
document.addEventListener('keydown',e=>{
 if(e.repeat)return; const key=e.key===' '?' ':e.key==='Tab'?'\\t':e.key.toLowerCase();
 if(key===' '){e.preventDefault();return stop()}
 if(key==='m'){e.preventDefault();return mark()}
 if('wasdrfqeocg\\t'.includes(key)){e.preventDefault();k(key)}
});
async function poll(){
 try{const s=await (await fetch('/state')).json(),p=s.pose;
  document.getElementById('st').innerHTML=
   `<tr><td>x</td><td>${p.x.toFixed(0)}</td><td>y</td><td>${p.y.toFixed(0)}</td><td>z</td><td>${p.z.toFixed(0)}</td></tr>`+
   `<tr><td>o</td><td colspan=3>(${p.o_x.toFixed(2)}, ${p.o_y.toFixed(2)}, ${p.o_z.toFixed(2)})</td><td>&theta;</td><td>${p.theta.toFixed(0)}</td></tr>`+
   `<tr><td>gripper</td><td>${(s.gripper??0).toFixed(0)}</td><td>last err</td><td class="${(s.last.err_mm||0)>2?'warn':''}">${s.last.err_mm??'-'} mm</td><td></td><td></td></tr>`;
  document.getElementById('busy').className=s.busy?'b':'';
  document.getElementById('step').textContent=`step ${s.step_mm} mm`;
  document.getElementById('logname').textContent=s.log;
  document.getElementById('lines').textContent=s.lines.join('\\n');
 }catch(e){}
 setTimeout(poll,400)}
function cam(){const i=document.getElementById('cam'),n=new Image();n.onload=()=>{i.src=n.src;setTimeout(cam,300)};n.onerror=()=>setTimeout(cam,1000);n.src='/frame.jpg?'+Date.now()}
poll();cam();
</script></body></html>"""


if __name__ == "__main__":
    web.run_app(build_app(), host="127.0.0.1", port=PORT, print=lambda *_: print(f"dashboard on http://localhost:{PORT}"))
