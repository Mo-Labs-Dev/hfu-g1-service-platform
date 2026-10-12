
import Link from "next/link";

type PlaceholderPageProps = {
  title: string;
  description?: string;
};

export default function PlaceholderPage({
  title,
  description = "This feature is under development.",
}: PlaceholderPageProps) {
  return (
    <div className="min-h-[70vh] bg-[#f7f9f8] px-6 py-12">
      <div className="mx-auto max-w-4xl rounded-2xl border border-slate-200 bg-white p-8 shadow-sm">
        <p className="text-xs font-semibold uppercase tracking-widest text-emerald-700">
          G1 Studio
        </p>

        <h1 className="mt-3 text-3xl font-bold text-slate-900">
          {title}
        </h1>

        <p className="mt-3 text-slate-500">
          {description}
        </p>

        <Link
          href="/studio"
          className="mt-6 inline-flex rounded-lg bg-emerald-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800"
        >
          Back to Studio
        </Link>
      </div>
    </div>
  );
}
