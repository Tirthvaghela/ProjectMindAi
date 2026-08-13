import { useCallback, useEffect, useRef, useState } from 'react'

function recognitionCtor() {
  if (typeof window === 'undefined') return null
  return window.SpeechRecognition || window.webkitSpeechRecognition || null
}

/**
 * Thin wrapper over the browser's SpeechRecognition API.
 *
 * Not supported everywhere (notably Firefox as of writing), so `supported`
 * lets the caller hide the mic entirely rather than show a button that always
 * fails. One recognition session per `start()` call — `continuous` stays
 * false because a single search query is a short phrase, not dictation.
 */
export function useVoiceSearch({ lang = 'en-US' } = {}) {
  const [listening, setListening] = useState(false)
  const [error, setError] = useState(null)
  const recognitionRef = useRef(null)
  const supported = Boolean(recognitionCtor())

  useEffect(() => {
    // Unmounting mid-listen (e.g. navigating away) should stop the mic, not
    // leave it recording into a component that no longer exists.
    return () => recognitionRef.current?.stop()
  }, [])

  const start = useCallback(
    (onResult) => {
      const Ctor = recognitionCtor()
      if (!Ctor) {
        setError('Voice search is not supported in this browser.')
        return
      }

      setError(null)
      const recognition = new Ctor()
      recognition.lang = lang
      recognition.interimResults = false
      recognition.maxAlternatives = 1

      recognition.onresult = (event) => {
        const transcript = event.results?.[0]?.[0]?.transcript ?? ''
        if (transcript.trim()) onResult(transcript.trim())
      }
      recognition.onerror = (event) => {
        // 'no-speech' and 'aborted' are ordinary (silence, or the user
        // stopped it deliberately) — not worth surfacing as an error.
        if (event.error !== 'no-speech' && event.error !== 'aborted') {
          setError('Could not hear you — check microphone permissions and try again.')
        }
      }
      recognition.onend = () => setListening(false)

      recognitionRef.current = recognition
      recognition.start()
      setListening(true)
    },
    [lang],
  )

  const stop = useCallback(() => recognitionRef.current?.stop(), [])

  return { supported, listening, error, start, stop }
}

export default useVoiceSearch
