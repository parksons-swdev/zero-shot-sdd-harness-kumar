'use client'

import Link from 'next/link'

/**
 * "Recent Datasets" nav item.
 *
 * Phase 2 (`frontend-dataset-reselect` slice): replaces the former Phase 1
 * disabled "Dataset Library — coming soon" placeholder with a working link to
 * the /datasets screen, where a previously uploaded dataset can be reopened
 * without re-uploading or re-profiling.
 */
export default function NavStub() {
  return (
    <Link href="/datasets" className="text-gray-600 hover:text-gray-900">
      Recent Datasets
    </Link>
  )
}
