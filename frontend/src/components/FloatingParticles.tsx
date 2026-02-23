export function FloatingParticles() {
  const particles = Array.from({ length: 20 }, (_, i) => ({
    id: i,
    size: Math.random() * 4 + 2,
    left: Math.random() * 100,
    top: Math.random() * 100,
    delay: Math.random() * 10,
    duration: Math.random() * 20 + 20,
  }));

  return (
    <div className="absolute inset-0 overflow-hidden pointer-events-none">
      {particles.map((particle) => (
        <div
          key={particle.id}
          className="absolute rounded-full bg-white/10 backdrop-blur-sm animate-float-particle"
          style={{
            width: `${particle.size}px`,
            height: `${particle.size}px`,
            left: `${particle.left}%`,
            top: `${particle.top}%`,
            animationDelay: `${particle.delay}s`,
            animationDuration: `${particle.duration}s`,
            boxShadow: '0 0 20px rgba(255, 255, 255, 0.1)',
          }}
        />
      ))}
      
      {/* Subtle blur shapes */}
      <div
        className="absolute w-96 h-96 rounded-full blur-3xl opacity-20 animate-float-blob"
        style={{
          background: 'radial-gradient(circle, rgba(76, 111, 255, 0.3) 0%, transparent 70%)',
          top: '20%',
          left: '10%',
        }}
      />
      <div
        className="absolute w-96 h-96 rounded-full blur-3xl opacity-20 animate-float-blob-reverse"
        style={{
          background: 'radial-gradient(circle, rgba(167, 139, 250, 0.3) 0%, transparent 70%)',
          bottom: '20%',
          right: '10%',
          animationDelay: '5s',
        }}
      />
    </div>
  );
}
