import { Link } from 'react-router-dom';

export default function LandingPage() {
  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-50 to-white overflow-y-auto overflow-x-hidden fixed inset-0">
      {/* Header */}
      <header className="fixed top-0 left-0 right-0 bg-white/80 backdrop-blur-md border-b border-gray-100 z-50">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            <div className="flex items-center gap-2">
              <img src="/images/logos/logo.webp" alt="Podly" className="h-8 w-auto" />
              <span className="text-xl font-bold text-gray-900">Podly</span>
            </div>
            <nav className="hidden md:flex items-center gap-8">
              <a href="#checklist" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
                Checklist
              </a>
              <a href="#how-it-works" className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors">
                How it works
              </a>
              <a
                href="https://github.com/jdrbc/podly_pure_podcasts"
                target="_blank"
                rel="noopener noreferrer"
                className="text-sm font-medium text-gray-600 hover:text-gray-900 transition-colors"
              >
                GitHub
              </a>
            </nav>
            <Link to="/login" className="bg-blue-600 hover:bg-blue-700 text-white px-5 py-2 rounded-lg font-medium transition-colors shadow-sm">
              Sign In
            </Link>
          </div>
        </div>
      </header>

      {/* Hero */}
      <section className="pt-32 pb-12 px-4 sm:px-6 lg:px-8">
        <div className="max-w-6xl mx-auto grid gap-12 lg:grid-cols-2 items-center">
          <div>
            <h1 className="text-4xl sm:text-5xl font-bold text-gray-900 leading-tight mb-6">
              Create an ad-free RSS feed.
            </h1>
            <p className="text-lg text-gray-600 mb-6 max-w-2xl">
              Podly downloads the episodes you care about, transcribes them with Whisper, removes sponsor reads with an LLM, and gives you a clean RSS link that works in any player. Pricing is simple: $1 per feed per month billed through Stripe.
            </p>
            <div className="flex flex-wrap gap-4 text-sm text-gray-700 mb-8">
              <span className="inline-flex items-center gap-2 bg-emerald-50 text-emerald-700 px-4 py-2 rounded-xl">
                <span className="h-2 w-2 rounded-full bg-emerald-500" />
                $1 / feed / month billed via Stripe
              </span>
              <span className="inline-flex items-center gap-2 bg-indigo-50 text-indigo-700 px-4 py-2 rounded-xl">
                <span className="h-2 w-2 rounded-full bg-indigo-500" />
                Works with any RSS-friendly player
              </span>
            </div>
            <div className="flex flex-col sm:flex-row items-center gap-4">
              <Link to="/login" className="w-full sm:w-auto bg-blue-600 hover:bg-blue-700 text-white px-8 py-4 rounded-xl font-semibold text-lg transition-colors shadow-lg hover:shadow-xl">
                Sign up
              </Link>
              <a href="#how-it-works" className="w-full sm:w-auto bg-white hover:bg-gray-50 text-gray-900 px-8 py-4 rounded-xl font-semibold text-lg border border-gray-200 transition-colors">
                See how it works
              </a>
            </div>
          </div>

          <div className="bg-white rounded-3xl border border-gray-100 shadow-xl p-8">
            <p className="text-sm font-semibold uppercase tracking-wide text-gray-500 mb-6">Clean feed checklist</p>
            <ol className="space-y-6">
              {[
                {
                  title: 'Sign up',
                  desc: 'Use Discord to sign up.',
                },
                {
                  title: 'Add a podcast',
                  desc: 'Use the search to find a podcast & add it to Podly.',
                },
                {
                  title: 'Subscribe to the clean RSS link',
                  desc: 'Copy the Podly URL so your own podcast apps stream the cleaned audio automatically.',
                },
              ].map((item, idx) => (
                <li key={item.title} className="flex gap-4">
                  <span className="flex h-10 w-10 items-center justify-center rounded-2xl bg-blue-50 text-blue-700 font-semibold">{idx + 1}</span>
                  <div>
                    <p className="font-semibold text-gray-900">{item.title}</p>
                    <p className="text-sm text-gray-600 mt-1 leading-relaxed">{item.desc}</p>
                  </div>
                </li>
              ))}
            </ol>
            <a href="https://discord.gg/FRB98GtF6N" target="_blank" rel="noopener noreferrer" className="mt-8 inline-flex items-center gap-2 text-sm font-medium text-blue-600">
              Need help? Join the Discord →
            </a>
          </div>
        </div>
      </section>

      {/* How it works */}
      <section id="how-it-works" className="pt-12 pb-16 px-4 sm:px-6 lg:px-8">
        <div className="max-w-6xl mx-auto space-y-12">
          <div className="text-center">
            <h2 className="text-3xl sm:text-4xl font-bold text-gray-900 mb-4">How it works</h2>
            <p className="text-lg text-gray-600 max-w-3xl mx-auto">Podly grabs the feed you nominate, finds sponsorship blocks automatically, and gives you a private RSS link so your own players stream the cleaned versions.</p>
          </div>
          <div className="grid gap-6 lg:grid-cols-2">
            <div className="rounded-2xl border border-gray-100 bg-white p-6">
              <p className="text-sm font-semibold uppercase tracking-wide text-gray-500 mb-4">Listen anywhere</p>
              <ul className="space-y-3 text-sm text-gray-600">
                <li><strong className="text-gray-900">Apple Podcasts:</strong> Library → Edit → Add Show by URL → paste the Podly link.</li>
                <li><strong className="text-gray-900">Overcast:</strong> Tap + → Add URL → paste → done.</li>
                <li><strong className="text-gray-900">Pocket Casts:</strong> Discover → Paste RSS Link → Subscribe.</li>
                <li><strong className="text-gray-900">Other players:</strong> Podcast Addict, AntennaPod, Castro, etc. all support “add via URL.”</li>
              </ul>
              <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/70 p-3 text-sm text-amber-900">
                Spotify blocks custom RSS feeds, so switch to any other podcast app when you use Podly links.
              </div>
            </div>
            <div className="rounded-2xl border border-blue-100 bg-blue-50/60 p-6">
              <p className="text-sm font-semibold uppercase tracking-wide text-blue-900 mb-4">Credits & support</p>
              <ul className="space-y-3 text-sm text-blue-900/90">
                <li>Pick how many feeds you want cleaned and pay 1 per feed each month with Stripe.</li>
                <li>Only see the feeds you add; keep your queue tidy without global noise.</li>
                <li>Admins can still view every feed for support while users stay scoped to their own.</li>
                <li>
                  Want help or to self-host? Deploy from{' '}
                  <a href="https://github.com/jdrbc/podly_pure_podcasts" className="underline font-semibold" target="_blank" rel="noopener noreferrer">
                    GitHub
                  </a>{' '}
                  and ask questions in{' '}
                  <a href="https://discord.gg/FRB98GtF6N" className="underline font-semibold" target="_blank" rel="noopener noreferrer">
                    Discord
                  </a>
                  .
                </li>
              </ul>
            </div>
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="py-10 sm:py-14 px-4 sm:px-6 lg:px-8">
        <div className="max-w-4xl mx-auto text-center">
          <div className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Link
              to="/login"
              className="w-full sm:w-auto bg-blue-600 hover:bg-blue-700 text-white px-8 py-4 rounded-xl font-semibold text-lg transition-colors shadow-lg hover:shadow-xl"
            >
              Sign up now
            </Link>
            <a
              href="https://discord.gg/FRB98GtF6N"
              target="_blank"
              rel="noopener noreferrer"
              className="w-full sm:w-auto flex items-center justify-center gap-2 bg-[#5865F2] hover:bg-[#4752C4] text-white px-8 py-4 rounded-xl font-semibold text-lg transition-colors"
            >
              <svg className="h-5 w-5" viewBox="0 0 24 24" fill="currentColor">
                <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
              </svg>
              Need help? Discord
            </a>
          </div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-4 sm:px-6 lg:px-8 border-t border-gray-200">
        <div className="max-w-6xl mx-auto">
          <div className="flex flex-col md:flex-row items-center justify-between gap-6">
            <div className="flex items-center gap-2">
              <img src="/images/logos/logo.webp" alt="Podly" className="h-6 w-auto" />
              <span className="font-semibold text-gray-900">Podly</span>
            </div>
            <p className="text-sm text-gray-500">
              Open source podcast ad remover.
            </p>
            <div className="flex items-center gap-4">
              <a
                href="https://github.com/jdrbc/podly_pure_podcasts"
                target="_blank"
                rel="noopener noreferrer"
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <svg className="h-6 w-6" fill="currentColor" viewBox="0 0 24 24">
                  <path fillRule="evenodd" d="M12 2C6.477 2 2 6.484 2 12.017c0 4.425 2.865 8.18 6.839 9.504.5.092.682-.217.682-.483 0-.237-.008-.868-.013-1.703-2.782.605-3.369-1.343-3.369-1.343-.454-1.158-1.11-1.466-1.11-1.466-.908-.62.069-.608.069-.608 1.003.07 1.531 1.032 1.531 1.032.892 1.53 2.341 1.088 2.91.832.092-.647.35-1.088.636-1.338-2.22-.253-4.555-1.113-4.555-4.951 0-1.093.39-1.988 1.029-2.688-.103-.253-.446-1.272.098-2.65 0 0 .84-.27 2.75 1.026A9.564 9.564 0 0112 6.844c.85.004 1.705.115 2.504.337 1.909-1.296 2.747-1.027 2.747-1.027.546 1.379.202 2.398.1 2.651.64.7 1.028 1.595 1.028 2.688 0 3.848-2.339 4.695-4.566 4.943.359.309.678.92.678 1.855 0 1.338-.012 2.419-.012 2.747 0 .268.18.58.688.482A10.019 10.019 0 0022 12.017C22 6.484 17.522 2 12 2z" clipRule="evenodd" />
                </svg>
              </a>
              <a
                href="https://discord.gg/FRB98GtF6N"
                target="_blank"
                rel="noopener noreferrer"
                className="text-gray-400 hover:text-gray-600 transition-colors"
              >
                <svg className="h-6 w-6" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028 14.09 14.09 0 0 0 1.226-1.994.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03zM8.02 15.33c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.956-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.956 2.418-2.157 2.418zm7.975 0c-1.183 0-2.157-1.085-2.157-2.419 0-1.333.955-2.419 2.157-2.419 1.21 0 2.176 1.096 2.157 2.42 0 1.333-.946 2.418-2.157 2.418z"/>
                </svg>
              </a>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
