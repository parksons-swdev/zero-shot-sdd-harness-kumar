'use client'

/**
 * "Dataset Library" nav item — Phase 1 labelled, non-functional stub.
 *
 * Replaced in Phase 2 (`frontend-dataset-reselect` slice) by a real "Recent
 * Datasets" picker. Deliberately disabled and visually muted so it reads as
 * an intentional preview of a future feature, never a broken control.
 */
export default function NavStub() {
  return (
    <span className="group relative inline-flex items-center">
      <button
        type="button"
        disabled
        aria-disabled="true"
        title="Dataset Library — coming soon"
        className="inline-flex cursor-not-allowed items-center gap-1.5 rounded-md border border-dashed border-gray-300 bg-gray-100 px-2.5 py-1 text-sm text-gray-400"
      >
        Dataset Library
        <span className="rounded-full bg-gray-200 px-1.5 py-0.5 text-[10px] font-medium tracking-wide text-gray-500 uppercase">
          Coming soon
        </span>
      </button>
    </span>
  )
}
