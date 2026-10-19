/* 台股羅盤 視覺效果（參考 React Bits 的 Aurora / Spotlight Card / Count Up / Animated List / Star Border 自行實作的輕量版，無外部套件） */
"use strict";
const FX = (() => {
  const reduce = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ------------------------------------------------------------------ 極光背景（WebGL）
  function aurora() {
    const cv = document.createElement("canvas");
    cv.id = "aurora";
    cv.setAttribute("aria-hidden", "true");
    document.body.prepend(cv);
    const gl = cv.getContext("webgl", { premultipliedAlpha: false, antialias: false });
    if (!gl) { cv.remove(); return; }
    const vs = `attribute vec2 p;void main(){gl_Position=vec4(p,0.,1.);}`;
    const fs = `precision mediump float;
uniform vec2 r;uniform float t;uniform vec3 c1;uniform vec3 c2;uniform vec3 c3;uniform float amp;
vec3 perm(vec3 x){return mod(((x*34.)+1.)*x,289.);}
float sn(vec2 v){const vec4 C=vec4(.211324865,.366025404,-.577350269,.024390244);
 vec2 i=floor(v+dot(v,C.yy));vec2 x0=v-i+dot(i,C.xx);vec2 i1=(x0.x>x0.y)?vec2(1.,0.):vec2(0.,1.);
 vec4 x12=x0.xyxy+C.xxzz;x12.xy-=i1;i=mod(i,289.);
 vec3 p=perm(perm(i.y+vec3(0.,i1.y,1.))+i.x+vec3(0.,i1.x,1.));
 vec3 m=max(.5-vec3(dot(x0,x0),dot(x12.xy,x12.xy),dot(x12.zw,x12.zw)),0.);m=m*m;m=m*m;
 vec3 x=2.*fract(p*C.www)-1.;vec3 h=abs(x)-.5;vec3 ox=floor(x+.5);vec3 a0=x-ox;
 m*=1.79284291400159-.85373472095314*(a0*a0+h*h);
 vec3 g;g.x=a0.x*x0.x+h.x*x0.y;g.yz=a0.yz*x12.xz+h.yz*x12.yw;return 130.*dot(m,g);}
void main(){vec2 uv=gl_FragCoord.xy/r;
 float n1=sn(vec2(uv.x*1.6+t*.05,t*.07))*.5+.5;
 float n2=sn(vec2(uv.x*2.3-t*.04,t*.05+3.))*.5+.5;
 float band1=smoothstep(.0,.55,1.-abs(uv.y-(.72+.18*n1-.1)))*1.;
 float band2=smoothstep(.0,.6,1.-abs(uv.y-(.58+.2*n2)));
 vec3 col=mix(c1,c2,smoothstep(.2,.8,uv.x+.2*n1));
 col=mix(col,c3,smoothstep(.55,1.,n2)*.6);
 float a=pow(band1,3.)*.55+pow(band2,4.)*.35;
 a*=smoothstep(.0,.45,uv.y)*amp;
 gl_FragColor=vec4(col,a);}`;
    const sh = (type, src) => { const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s); return s; };
    const pr = gl.createProgram();
    gl.attachShader(pr, sh(gl.VERTEX_SHADER, vs)); gl.attachShader(pr, sh(gl.FRAGMENT_SHADER, fs)); gl.linkProgram(pr);
    if (!gl.getProgramParameter(pr, gl.LINK_STATUS)) { cv.remove(); return; }
    gl.useProgram(pr);
    const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
    const loc = gl.getAttribLocation(pr, "p"); gl.enableVertexAttribArray(loc); gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
    gl.enable(gl.BLEND); gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    const U = (n) => gl.getUniformLocation(pr, n);
    const uR = U("r"), uT = U("t"), u1 = U("c1"), u2 = U("c2"), u3 = U("c3"), uA = U("amp");
    const hex = (h) => { h = h.trim().replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255); };
    function colors() {
      const cs = getComputedStyle(document.documentElement);
      gl.uniform3fv(u1, hex(cs.getPropertyValue("--au1") || "#1fb5c9"));
      gl.uniform3fv(u2, hex(cs.getPropertyValue("--au2") || "#6a5cff"));
      gl.uniform3fv(u3, hex(cs.getPropertyValue("--au3") || "#e2b45a"));
      gl.uniform1f(uA, parseFloat(cs.getPropertyValue("--au-amp")) || 1);
    }
    function size() {
      const s = 0.5; // 半解析度即可，省效能
      cv.width = Math.max(2, innerWidth * s | 0); cv.height = Math.max(2, innerHeight * s | 0);
      gl.viewport(0, 0, cv.width, cv.height); gl.uniform2f(uR, cv.width, cv.height);
    }
    size(); colors();
    addEventListener("resize", size);
    new MutationObserver(colors).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    matchMedia("(prefers-color-scheme: dark)").addEventListener?.("change", colors);
    let last = 0, t0 = performance.now();
    function frame(now) {
      if (!document.hidden && now - last > 33) {
        last = now;
        gl.clearColor(0, 0, 0, 0); gl.clear(gl.COLOR_BUFFER_BIT);
        gl.uniform1f(uT, reduce ? 12 : (now - t0) / 1000);
        gl.drawArrays(gl.TRIANGLES, 0, 3);
      }
      if (!reduce) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  // ------------------------------------------------------------------ 聚光燈卡片
  function spotlight() {
    document.addEventListener("pointermove", (e) => {
      const c = e.target.closest && e.target.closest(".card, .hzbox, .tile");
      if (!c) return;
      const r = c.getBoundingClientRect();
      c.style.setProperty("--mx", (e.clientX - r.left) + "px");
      c.style.setProperty("--my", (e.clientY - r.top) + "px");
    }, { passive: true });
  }

  // ------------------------------------------------------------------ 數字滾動
  function countUp(root) {
    const els = root.querySelectorAll("[data-count]");
    els.forEach((el) => {
      const to = parseFloat(el.dataset.count);
      if (isNaN(to)) return;
      const dec = +(el.dataset.dec || 0);
      const fmt = (v) => v.toLocaleString("zh-TW", { minimumFractionDigits: dec, maximumFractionDigits: dec });
      if (reduce) { el.textContent = fmt(to); return; }
      const from = parseFloat(el.dataset.from || (Math.abs(to) > 1000 ? to * 0.96 : 0));
      const dur = 900, t0 = performance.now();
      const step = (now) => {
        const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
        el.textContent = fmt(from + (to - from) * e);
        if (k < 1) requestAnimationFrame(step);
      };
      requestAnimationFrame(step);
    });
  }

  // ------------------------------------------------------------------ 清單逐列浮現
  function stagger(root) {
    if (reduce) return;
    const rows = root.querySelectorAll(".list > .row:not(.head), .bars > .b, .tbl tbody tr, .facts li");
    rows.forEach((r, i) => {
      if (i > 40) return;
      r.style.animationDelay = (Math.min(i, 20) * 28) + "ms";
      r.classList.add("rise");
    });
  }

  // ------------------------------------------------------------------ 跑馬燈
  function ticker(el, items) {
    if (!items || !items.length) { el.classList.add("hide"); return; }
    const html = items.map((x) => `<a class="tk" href="${x.href}"><b>${x.n}</b><span class="num">${x.px}</span><span class="num ${x.cls}">${x.chg}</span></a>`).join("");
    el.innerHTML = `<div class="tk-track">${html}${html}</div>`;
    el.classList.remove("hide");
    const track = el.firstChild;
    const w = track.scrollWidth / 2;
    track.style.setProperty("--tk-dist", -w + "px");
    track.style.animationDuration = Math.max(30, w / 45) + "s";
  }

  function enhance(root) { countUp(root); stagger(root); }

  function init() { aurora(); spotlight(); }
  return { init, enhance, ticker, reduce };
})();
