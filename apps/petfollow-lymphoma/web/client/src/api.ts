export type Exam = {
  exam_id: string; patient_pseudo_id: string; study_datetime: string;
  prior_exam_id: string | null; is_synthetic?: boolean; attenuation_corrected: boolean;
  manual_input?: { version: number; watermark: string; source_a: string; source_b: string; reviewer: string } | null
}
export type Lesion = { lesion_id: string; label: string; lesion_track_id?: string | null; status: string }
export type Measurement = { lesion_id: string; suv_max: number | null; longest_diameter_mm: number | null; ct_long_mm: number | null; ct_short_mm: number | null; ct_spd_mm2: number | null; ct_dimensions_note?: string; state: string; edited?: boolean }
export type CompareRow = { lesion_id: string | null; prior_lesion_id: string | null; label: string; prior_label: string | null; current_suv: number | null; prior_suv: number | null; delta_suv: number | null; delta_suv_pct: number | null; current_mm: number | null; prior_mm: number | null; delta_mm: number | null; current_spd: number | null; prior_spd: number | null; delta_spd_pct: number | null; status: string }
export type State = {
  exam: Exam; exams: Exam[]; lesions: Lesion[]; measurements: Measurement[];
  prior: Exam | null; prior_lesions: Lesion[]; rows: CompareRow[]; candidates: Exam[];
  pet_count: number; ct_count: number; pet_shape: number[]; ct_shape: number[];
  exam_counts: Record<string, { pet: number; ct: number }>;
  exam_shapes: Record<string, { pet: number[]; ct: number[] }>;
  correction_label: string; gates: { level: string; message: string }[];
  references: Partial<Record<'blood_pool' | 'liver', Reference>>;
  assessments: Record<string, Assessment>
}
export type Roi = { index: number; seed: [number, number]; fraction: number; label: string; image: string }
export type Report = { generated: string; description: string; confirmed_appendix: string; gates: { level: string; message: string }[] }
export type Alignment = { base_exam_id: string; current_exam_id: string; offset_mm: number[]; offset_along_normal_mm: number; slice_locations: Record<'basePet' | 'currentPet' | 'baseCt' | 'currentCt', number[]> }
export type Reference = { kind: 'blood_pool' | 'liver'; version: number; suv_max: number | null; suv_mean: number | null; raw_max: number; raw_mean: number; raw_units: string; voxel_count: number; note: string; placement_confirmed: boolean; confirmed_by?: string; confirmed_at?: string }
export type Assessment = { suggestion: string; fingerprint: string; stale: boolean; confirmed: null | { version: number; score: string; category: string; reviewer: string; reason: string; confirmed_at: string }; evidence: { current_suv_max: number | null; prior_suv_max: number | null; delta_suv_pct: number | null } }

export async function api<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, body === undefined ? undefined : {
    method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body),
  })
  if (!response.ok) {
    let message = `请求失败 (${response.status})`
    try { message = (await response.json()).error || message } catch { /* response might be HTML */ }
    throw new Error(message)
  }
  return response.json()
}

export const imageUrl = (examId: string, modality: 'pet' | 'ct' | 'fusion', index: number, center: number, width: number, petMax: number) =>
  `/api/image?exam_id=${encodeURIComponent(examId)}&modality=${modality}&index=${index}&center=${center}&width=${width}&pet_max=${petMax}`

export const number = (n: number | null | undefined, digits = 2) =>
  n == null ? '—' : n.toFixed(digits)
