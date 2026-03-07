import { useState, useEffect } from 'react';

interface TypewriterEffectProps {
  phrases: string[];
}

export function TypewriterEffect({ phrases }: TypewriterEffectProps) {
  const [currentPhraseIndex, setCurrentPhraseIndex] = useState(0);
  const [currentText, setCurrentText] = useState('');
  const [isDeleting, setIsDeleting] = useState(false);
  const [isPaused, setIsPaused] = useState(false);
  const [showCursor, setShowCursor] = useState(true);

  useEffect(() => {
    // Cursor blink effect
    const cursorInterval = setInterval(() => {
      setShowCursor((prev) => !prev);
    }, 530);

    return () => clearInterval(cursorInterval);
  }, []);

  useEffect(() => {
    const currentPhrase = phrases[currentPhraseIndex];

    if (isPaused) {
      const pauseTimer = setTimeout(() => {
        setIsPaused(false);
        setIsDeleting(true);
      }, 2000); // Pause for 2 seconds before deleting

      return () => clearTimeout(pauseTimer);
    }

    if (!isDeleting && currentText === currentPhrase) {
      setIsPaused(true);
      return;
    }

    if (isDeleting && currentText === '') {
      setIsDeleting(false);
      setCurrentPhraseIndex((prev) => (prev + 1) % phrases.length);
      return;
    }

    const typingSpeed = isDeleting ? 50 : 100; // Faster when deleting
    const timer = setTimeout(() => {
      if (isDeleting) {
        setCurrentText(currentPhrase.substring(0, currentText.length - 1));
      } else {
        setCurrentText(currentPhrase.substring(0, currentText.length + 1));
      }
    }, typingSpeed);

    return () => clearTimeout(timer);
  }, [currentText, isDeleting, isPaused, currentPhraseIndex, phrases]);

  return (
    <div className="min-h-[120px]">
      <h1 className="text-5xl xl:text-6xl font-bold text-white leading-tight">
        <span className="inline-block bg-gradient-to-r from-white via-white to-[#A78BFA] bg-clip-text text-transparent drop-shadow-[0_0_30px_rgba(167,139,250,0.3)]">
          {currentText}
        </span>
        <span
          className={`inline-block w-1 h-14 ml-1 bg-[#4C6FFF] align-middle transition-opacity duration-100 ${
            showCursor ? 'opacity-100' : 'opacity-0'
          }`}
          style={{ 
            boxShadow: '0 0 20px rgba(76, 111, 255, 0.5)',
            transform: 'translateY(-2px)'
          }}
        />
      </h1>
    </div>
  );
}
