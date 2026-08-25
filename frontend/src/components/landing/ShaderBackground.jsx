import { useEffect, useRef } from 'react'

const VERTEX_SHADER = `attribute vec2 a_position;
varying vec2 v_texCoord;
void main() {
  v_texCoord = a_position * 0.5 + 0.5;
  gl_Position = vec4(a_position, 0.0, 1.0);
}`

const FRAGMENT_SHADER = `precision highp float;
varying vec2 v_texCoord;
uniform float u_time;
uniform vec2 u_resolution;

float noise(vec2 p) {
    return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453);
}

void main() {
    vec2 uv = v_texCoord;
    float t = u_time * 0.1;

    float noise1 = noise(uv * 3.0 + t);
    float noise2 = noise(uv * 6.0 - t * 0.5);

    float strength = smoothstep(0.4, 0.6, (noise1 + noise2) * 0.5);

    vec3 color1 = vec3(0.02, 0.02, 0.02);
    vec3 color2 = vec3(0.15, 0.15, 0.15);

    vec3 finalColor = mix(color1, color2, strength);

    float scanline = sin(uv.y * 800.0) * 0.02;
    finalColor += scanline;

    gl_FragColor = vec4(finalColor, 1.0);
}`

function compileShader(gl, type, source) {
  const shader = gl.createShader(type)
  gl.shaderSource(shader, source)
  gl.compileShader(shader)
  return shader
}

/**
 * Liquid-metal monochrome noise field, straight WebGL (no library) — a
 * faithful port of the reference mockup's background shader. Lives behind
 * the landing hero only; see DESIGN.md for the "Premium Lab" visual brief
 * this serves.
 */
export default function ShaderBackground({ className }) {
  const canvasRef = useRef(null)

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return

    const syncSize = () => {
      const w = canvas.clientWidth || 1280
      const h = canvas.clientHeight || 720
      if (canvas.width !== w || canvas.height !== h) {
        canvas.width = w
        canvas.height = h
      }
    }

    let resizeObserver
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(syncSize)
      resizeObserver.observe(canvas)
    }
    syncSize()

    // This is purely decorative texture behind the hero copy — on a lost or
    // unavailable context (low-power mode, driver crash, a browser with no
    // WebGL), the right fallback is just "no shader," not the browser's own
    // broken-context glyph left sitting on top of the hero. preventDefault()
    // on the loss event stops that native indicator; hiding the canvas is
    // the actual fallback, and the section's own dark gradient/backdrop
    // already reads fine underneath with nothing here at all.
    const handleContextLost = (event) => {
      event.preventDefault()
      if (frameId) cancelAnimationFrame(frameId)
      canvas.style.display = 'none'
    }
    canvas.addEventListener('webglcontextlost', handleContextLost, false)

    const gl = canvas.getContext('webgl') || canvas.getContext('experimental-webgl')
    if (!gl) {
      canvas.style.display = 'none'
      return () => canvas.removeEventListener('webglcontextlost', handleContextLost)
    }

    const program = gl.createProgram()
    gl.attachShader(program, compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER))
    gl.attachShader(program, compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER))
    gl.linkProgram(program)
    gl.useProgram(program)

    const buffer = gl.createBuffer()
    gl.bindBuffer(gl.ARRAY_BUFFER, buffer)
    gl.bufferData(
      gl.ARRAY_BUFFER,
      new Float32Array([-1, -1, 1, -1, -1, 1, 1, 1]),
      gl.STATIC_DRAW,
    )
    const positionLoc = gl.getAttribLocation(program, 'a_position')
    gl.enableVertexAttribArray(positionLoc)
    gl.vertexAttribPointer(positionLoc, 2, gl.FLOAT, false, 0, 0)

    const uTime = gl.getUniformLocation(program, 'u_time')
    const uRes = gl.getUniformLocation(program, 'u_resolution')

    let frameId
    // Reduced motion: render one still frame instead of animating forever.
    const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

    const render = (t) => {
      if (!resizeObserver) syncSize()
      gl.viewport(0, 0, canvas.width, canvas.height)
      if (uTime) gl.uniform1f(uTime, t * 0.001)
      if (uRes) gl.uniform2f(uRes, canvas.width, canvas.height)
      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4)
      if (!prefersReducedMotion) frameId = requestAnimationFrame(render)
    }
    render(0)

    return () => {
      if (frameId) cancelAnimationFrame(frameId)
      resizeObserver?.disconnect()
      canvas.removeEventListener('webglcontextlost', handleContextLost)
      gl.getExtension('WEBGL_lose_context')?.loseContext()
    }
  }, [])

  return <canvas ref={canvasRef} className={className} />
}
