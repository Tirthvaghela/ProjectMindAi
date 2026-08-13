import { useEffect, useRef } from 'react'
import * as THREE from 'three'

/**
 * Rotating cluster of wireframe cubes behind the hero headline — a faithful
 * port of the reference mockup's Three.js scene. Vanilla Three.js rather
 * than a React wrapper library, to keep this port a direct, easy-to-diff
 * translation of the original script.
 */
export default function WireframeCubes({ className }) {
  const containerRef = useRef(null)

  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    const width = container.clientWidth || window.innerWidth
    const height = container.clientHeight || window.innerHeight

    const scene = new THREE.Scene()
    const camera = new THREE.PerspectiveCamera(75, width / height, 0.1, 1000)
    const renderer = new THREE.WebGLRenderer({ alpha: true, antialias: true })

    renderer.setSize(width, height)
    renderer.setPixelRatio(window.devicePixelRatio)
    container.appendChild(renderer.domElement)

    const group = new THREE.Group()
    const geometry = new THREE.BoxGeometry(1, 1, 1)
    const material = new THREE.MeshPhongMaterial({
      color: 0xffffff,
      wireframe: true,
      transparent: true,
      opacity: 0.3,
    })

    for (let i = 0; i < 12; i++) {
      const mesh = new THREE.Mesh(geometry, material)
      mesh.position.set((Math.random() - 0.5) * 4, (Math.random() - 0.5) * 4, (Math.random() - 0.5) * 4)
      mesh.rotation.set(Math.random(), Math.random(), Math.random())
      mesh.scale.setScalar(Math.random() * 2)
      group.add(mesh)
    }
    scene.add(group)

    const light = new THREE.DirectionalLight(0xffffff, 1)
    light.position.set(5, 5, 5)
    scene.add(light)
    scene.add(new THREE.AmbientLight(0x404040))

    camera.position.z = 8

    const prefersReducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    let frameId
    const animate = () => {
      frameId = requestAnimationFrame(animate)
      if (!prefersReducedMotion) {
        group.rotation.y += 0.002
        group.rotation.x += 0.001
      }
      renderer.render(scene, camera)
    }
    animate()

    const handleResize = () => {
      const w = container.clientWidth || window.innerWidth
      const h = container.clientHeight || window.innerHeight
      camera.aspect = w / h
      camera.updateProjectionMatrix()
      renderer.setSize(w, h)
    }
    window.addEventListener('resize', handleResize)

    return () => {
      cancelAnimationFrame(frameId)
      window.removeEventListener('resize', handleResize)
      geometry.dispose()
      material.dispose()
      renderer.dispose()
      if (renderer.domElement.parentNode === container) {
        container.removeChild(renderer.domElement)
      }
    }
  }, [])

  return <div ref={containerRef} className={className} />
}
