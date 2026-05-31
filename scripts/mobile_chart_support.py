from __future__ import annotations

import json
import re


CANVAS_TOUCH_SCRIPT = """
(function(){
  if(window.__yilimiCanvasTouchBound)return;
  window.__yilimiCanvasTouchBound=true;
  canvas.dataset.touchBound="1";
  let touchState=null;
  function touchPoint(event){
    const touch=(event.changedTouches&&event.changedTouches[0])||(event.touches&&event.touches[0]);
    return touch?{clientX:touch.clientX,clientY:touch.clientY}:null;
  }
  function fireMouse(type,point){
    canvas.dispatchEvent(new MouseEvent(type,{bubbles:true,cancelable:true,clientX:point.clientX,clientY:point.clientY,view:window}));
  }
  canvas.addEventListener("touchstart",event=>{
    if(event.touches.length!==1)return;
    event.preventDefault();
    const point=touchPoint(event);
    if(!point)return;
    touchState={x:point.clientX,y:point.clientY,moved:false};
    fireMouse("mousemove",point);
  },{passive:false});
  canvas.addEventListener("touchmove",event=>{
    if(!touchState||event.touches.length!==1)return;
    event.preventDefault();
    const point=touchPoint(event);
    if(!point)return;
    if(Math.hypot(point.clientX-touchState.x,point.clientY-touchState.y)>8)touchState.moved=true;
    fireMouse("mousemove",point);
  },{passive:false});
  canvas.addEventListener("touchend",event=>{
    if(!touchState)return;
    event.preventDefault();
    const point=touchPoint(event);
    if(point&&!touchState.moved)fireMouse("click",point);
    touchState=null;
  },{passive:false});
  canvas.addEventListener("touchcancel",()=>{
    touchState=null;
    tip.style.display="none";
    draw();
  },{passive:false});
})();
"""


CANVAS_MOBILE_STYLE = """
    @media (max-width: 640px){
      .home-link{left:10px;top:10px;width:38px;height:38px}
      .tip{max-width:calc(100dvw - 16px)}
    }
"""


def add_canvas_mobile_support(page: str) -> str:
    page = page.replace(
        'name="viewport" content="width=device-width,initial-scale=1"',
        'name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"',
    )
    page = page.replace(
        ".page{position:relative;width:100vw;height:100vh",
        ".page{position:relative;width:100vw;width:100dvw;height:100vh;height:100dvh",
    )
    page = page.replace(
        "canvas{display:block;width:100vw;height:100vh",
        "canvas{display:block;width:100vw;width:100dvw;height:100vh;height:100dvh;touch-action:none;-webkit-user-select:none;user-select:none",
    )
    page = re.sub(
        r"(\.tip\{[^}]*?)white-space:nowrap",
        r"\1box-sizing:border-box;max-width:calc(100dvw - 16px);overflow-wrap:anywhere;white-space:normal",
        page,
    )
    page = page.replace("</style>", CANVAS_MOBILE_STYLE + "</style>", 1)
    if CANVAS_TOUCH_SCRIPT not in page:
        page = page.replace("window.addEventListener(\"resize\",resize);", CANVAS_TOUCH_SCRIPT + "window.addEventListener(\"resize\",resize);", 1)
    return page


def add_plotly_mobile_support(
    page: str,
    desktop_margin: dict[str, int],
    tablet_margin: dict[str, int],
    phone_margin: dict[str, int],
) -> str:
    page = page.replace(
        'name="viewport" content="width=device-width,initial-scale=1"',
        'name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"',
    )
    page = page.replace(
        ".page{position:relative;width:100vw;height:100vh",
        ".page{position:relative;width:100vw;width:100dvw;height:100vh;height:100dvh",
    )
    page = page.replace(
        ".chart-frame{position:absolute;inset:0}",
        ".chart-frame{position:absolute;inset:0;touch-action:none}",
    )
    margins = {
        "desktop": desktop_margin,
        "tablet": tablet_margin,
        "phone": phone_margin,
    }
    script = f"""
<script>
(function(){{
  const margins={json.dumps(margins, separators=(",", ":"))};
  function layoutForViewport(){{
    const width=window.innerWidth;
    return width<=640?margins.phone:width<=1024?margins.tablet:margins.desktop;
  }}
  function resizePlotly(){{
    const graph=document.querySelector(".js-plotly-plot");
    if(!graph||!window.Plotly)return;
    Plotly.relayout(graph,{{margin:layoutForViewport()}}).then(()=>Plotly.Plots.resize(graph));
  }}
  window.addEventListener("resize",resizePlotly,{{passive:true}});
  window.addEventListener("orientationchange",()=>setTimeout(resizePlotly,180),{{passive:true}});
  requestAnimationFrame(resizePlotly);
}})();
</script>
"""
    return page.replace("</body>", script + "</body>", 1)
