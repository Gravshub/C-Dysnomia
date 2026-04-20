import { SearchBar } from '@/components/SearchBar';

export default function Home() {
  return (
    <main className="min-h-screen flex flex-col">
      <section className="flex-1 flex flex-col justify-center items-center px-6 py-20 text-center">
        <h1 className="text-5xl md:text-7xl brand-text font-bold mb-4 tracking-tight">
          PLSCAN LP
        </h1>
        <p className="text-text-secondary text-lg md:text-xl mb-10 max-w-xl">
          Explore any token's liquidity on PulseChain.
        </p>
        <SearchBar />
      </section>
      <footer className="py-6 text-center text-text-tertiary text-xs">
        Read-only. No wallet required. Chain 369.
      </footer>
    </main>
  );
}
