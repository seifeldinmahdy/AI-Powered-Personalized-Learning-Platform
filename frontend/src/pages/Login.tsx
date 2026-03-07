import { useState } from 'react';
import { useNavigate } from 'react-router';
import { Mail, Lock, ArrowRight, Sparkles, Loader2 } from 'lucide-react';
import { TypewriterEffect } from '../components/TypewriterEffect';
import { FloatingParticles } from '../components/FloatingParticles';
import { useAuth } from '../contexts/AuthContext';
import axios from 'axios';

export default function Login() {
  const navigate = useNavigate();
  const { login, signup } = useAuth();
  const [isLogin, setIsLogin] = useState(true);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [name, setName] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setLoading(true);

    try {
      if (isLogin) {
        await login(email, password);
      } else {
        await signup(name, email, password);
      }
      navigate('/dashboard');
    } catch (err) {
      if (axios.isAxiosError(err) && err.response?.data?.error) {
        setError(err.response.data.error);
      } else {
        setError('Something went wrong. Please try again.');
      }
    } finally {
      setLoading(false);
    }
  };

  const phrases = [
    "Your Personal AI Tutor.",
    "Learning That Adapts To You.",
    "Master Any Topic, Intelligently.",
  ];

  return (
    <div className="min-h-screen flex relative overflow-hidden bg-[#0a0b1e]">
      {/* Animated Gradient Background */}
      <div className="absolute inset-0 overflow-hidden">
        <div className="absolute inset-0 bg-gradient-to-br from-[#1E2A78] via-[#0a0b1e] to-[#1a1b3a] animate-gradient-shift" />
        <div className="absolute top-0 left-0 w-full h-full bg-gradient-to-tr from-[#4C6FFF]/20 via-transparent to-[#A78BFA]/20 animate-gradient-slow" />
        <div className="absolute -top-1/2 -left-1/2 w-full h-full bg-[#4C6FFF]/10 rounded-full blur-3xl animate-float-slow" />
        <div className="absolute -bottom-1/2 -right-1/2 w-full h-full bg-[#A78BFA]/10 rounded-full blur-3xl animate-float-slower" />
      </div>

      {/* Floating Particles */}
      <FloatingParticles />

      <div className="relative z-10 flex w-full">
        {/* Left Side - Marketing */}
        <div className="hidden lg:flex lg:w-1/2 flex-col justify-center px-16 xl:px-24">
          {/* Logo */}
          <div className="mb-12">
            <div className="inline-flex items-center gap-3 mb-8">
              <div className="relative">
                <div className="absolute inset-0 bg-gradient-to-br from-[#4C6FFF] to-[#A78BFA] blur-xl opacity-50" />
                <div className="relative w-14 h-14 rounded-2xl bg-gradient-to-br from-[#4C6FFF] to-[#A78BFA] flex items-center justify-center shadow-2xl">
                  <Sparkles className="text-white" size={28} />
                </div>
              </div>
              <div>
                <h2 className="text-white mb-0 text-2xl">AI Tutor</h2>
              </div>
            </div>
          </div>

          {/* Typewriter Effect */}
          <div className="mb-16">
            <TypewriterEffect phrases={phrases} />
          </div>

          {/* Supporting Text */}
          <div className="space-y-6 max-w-lg">
            <div className="flex items-start gap-4 group">
              <div className="w-10 h-10 rounded-lg bg-white/5 backdrop-blur-sm flex items-center justify-center flex-shrink-0 group-hover:bg-white/10 transition-all">
                <span className="text-2xl">🎯</span>
              </div>
              <div>
                <h4 className="text-white mb-1 text-base">Personalized Learning Paths</h4>
                <p className="text-white/60 text-sm leading-relaxed">AI adapts to your pace and style, creating a unique curriculum just for you.</p>
              </div>
            </div>

            <div className="flex items-start gap-4 group">
              <div className="w-10 h-10 rounded-lg bg-white/5 backdrop-blur-sm flex items-center justify-center flex-shrink-0 group-hover:bg-white/10 transition-all">
                <span className="text-2xl">⚡</span>
              </div>
              <div>
                <h4 className="text-white mb-1 text-base">Real-Time Feedback</h4>
                <p className="text-white/60 text-sm leading-relaxed">Get instant guidance and corrections as you learn, powered by advanced AI.</p>
              </div>
            </div>

            <div className="flex items-start gap-4 group">
              <div className="w-10 h-10 rounded-lg bg-white/5 backdrop-blur-sm flex items-center justify-center flex-shrink-0 group-hover:bg-white/10 transition-all">
                <span className="text-2xl">🧠</span>
              </div>
              <div>
                <h4 className="text-white mb-1 text-base">Intelligent Analytics</h4>
                <p className="text-white/60 text-sm leading-relaxed">Track your progress with detailed insights and personalized recommendations.</p>
              </div>
            </div>
          </div>

          {/* Stats */}
          <div className="mt-16 grid grid-cols-3 gap-8">
            <div>
              <p className="text-4xl font-bold text-white mb-1 bg-gradient-to-r from-[#4C6FFF] to-[#A78BFA] bg-clip-text text-transparent">10K+</p>
              <p className="text-white/60 text-sm">Active Learners</p>
            </div>
            <div>
              <p className="text-4xl font-bold text-white mb-1 bg-gradient-to-r from-[#A78BFA] to-[#4C6FFF] bg-clip-text text-transparent">98%</p>
              <p className="text-white/60 text-sm">Success Rate</p>
            </div>
            <div>
              <p className="text-4xl font-bold text-white mb-1 bg-gradient-to-r from-[#4C6FFF] to-[#A78BFA] bg-clip-text text-transparent">24/7</p>
              <p className="text-white/60 text-sm">AI Support</p>
            </div>
          </div>
        </div>

        {/* Right Side - Form */}
        <div className="w-full lg:w-1/2 flex items-center justify-center px-8 py-12">
          <div className="w-full max-w-md">
            {/* Card */}
            <div className="bg-white/95 backdrop-blur-xl rounded-2xl shadow-2xl p-8 border border-white/20">
              {/* Header */}
              <div className="mb-8">
                <h1 className="text-3xl font-bold text-[#1F2937] mb-2">
                  {isLogin ? 'Welcome Back' : 'Get Started'}
                </h1>
                <p className="text-[#6B7280]">
                  {isLogin
                    ? 'Continue your learning journey'
                    : 'Create your account and start learning'
                  }
                </p>
              </div>

              {/* Error Message */}
              {error && (
                <div className="mb-5 px-4 py-3 bg-red-50 border border-red-200 rounded-xl text-red-600 text-sm">
                  {error}
                </div>
              )}

              {/* Form */}
              <form onSubmit={handleSubmit} className="space-y-5">
                {!isLogin && (
                  <div>
                    <label htmlFor="name" className="block text-sm font-semibold text-[#1F2937] mb-2">
                      Full Name
                    </label>
                    <div className="relative">
                      <input
                        id="name"
                        type="text"
                        value={name}
                        onChange={(e) => setName(e.target.value)}
                        placeholder="Enter your full name"
                        className="w-full px-4 py-3.5 bg-[#F7F9FC] border-2 border-[#E5E7EB] rounded-xl text-[#1F2937] placeholder-[#9CA3AF] focus:outline-none focus:border-[#4C6FFF] focus:bg-white transition-all"
                        required
                        disabled={loading}
                      />
                    </div>
                  </div>
                )}

                <div>
                  <label htmlFor="email" className="block text-sm font-semibold text-[#1F2937] mb-2">
                    Email Address
                  </label>
                  <div className="relative">
                    <div className="absolute left-4 top-1/2 -translate-y-1/2 text-[#9CA3AF]">
                      <Mail size={20} />
                    </div>
                    <input
                      id="email"
                      type="email"
                      value={email}
                      onChange={(e) => setEmail(e.target.value)}
                      placeholder="you@example.com"
                      className="w-full pl-12 pr-4 py-3.5 bg-[#F7F9FC] border-2 border-[#E5E7EB] rounded-xl text-[#1F2937] placeholder-[#9CA3AF] focus:outline-none focus:border-[#4C6FFF] focus:bg-white transition-all"
                      required
                      disabled={loading}
                    />
                  </div>
                </div>

                <div>
                  <label htmlFor="password" className="block text-sm font-semibold text-[#1F2937] mb-2">
                    Password
                  </label>
                  <div className="relative">
                    <div className="absolute left-4 top-1/2 -translate-y-1/2 text-[#9CA3AF]">
                      <Lock size={20} />
                    </div>
                    <input
                      id="password"
                      type="password"
                      value={password}
                      onChange={(e) => setPassword(e.target.value)}
                      placeholder="Enter your password"
                      className="w-full pl-12 pr-4 py-3.5 bg-[#F7F9FC] border-2 border-[#E5E7EB] rounded-xl text-[#1F2937] placeholder-[#9CA3AF] focus:outline-none focus:border-[#4C6FFF] focus:bg-white transition-all"
                      required
                      disabled={loading}
                    />
                  </div>
                </div>

                {isLogin && (
                  <div className="flex items-center justify-between text-sm">
                    <label className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        className="w-4 h-4 rounded border-2 border-[#E5E7EB] text-[#4C6FFF] focus:ring-[#4C6FFF] focus:ring-offset-0"
                      />
                      <span className="text-[#6B7280]">Remember me</span>
                    </label>
                    <a href="#" className="text-[#4C6FFF] hover:text-[#A78BFA] font-semibold transition-colors">
                      Forgot password?
                    </a>
                  </div>
                )}

                <button
                  type="submit"
                  disabled={loading}
                  className="w-full py-4 bg-gradient-to-r from-[#4C6FFF] to-[#A78BFA] text-white font-semibold rounded-xl shadow-lg hover:shadow-xl hover:scale-[1.02] active:scale-[0.98] transition-all flex items-center justify-center gap-2 group disabled:opacity-70 disabled:cursor-not-allowed disabled:hover:scale-100"
                >
                  {loading ? (
                    <>
                      <Loader2 size={20} className="animate-spin" />
                      <span>{isLogin ? 'Signing In...' : 'Creating Account...'}</span>
                    </>
                  ) : (
                    <>
                      <span>{isLogin ? 'Sign In' : 'Create Account'}</span>
                      <ArrowRight size={20} className="group-hover:translate-x-1 transition-transform" />
                    </>
                  )}
                </button>

                {!isLogin && (
                  <p className="text-xs text-[#6B7280] text-center leading-relaxed">
                    By creating an account, you agree to our Terms of Service and Privacy Policy.
                  </p>
                )}
              </form>

              {/* Divider */}
              <div className="my-6 flex items-center gap-4">
                <div className="flex-1 h-px bg-[#E5E7EB]" />
                <span className="text-sm text-[#9CA3AF]">or</span>
                <div className="flex-1 h-px bg-[#E5E7EB]" />
              </div>

              {/* Toggle */}
              <button
                onClick={() => { setIsLogin(!isLogin); setError(''); }}
                className="w-full py-3.5 bg-[#F7F9FC] text-[#1F2937] font-semibold rounded-xl border-2 border-[#E5E7EB] hover:border-[#4C6FFF] hover:bg-white transition-all"
              >
                {isLogin ? "Don't have an account? Sign Up" : 'Already have an account? Sign In'}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
