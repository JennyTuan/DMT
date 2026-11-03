import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { Columns2, FileText, FolderOpen, History, Link2, Maximize2, MousePointer2, RotateCcw, Save, SlidersHorizontal, ZoomIn, ZoomOut } from 'lucide-react'
import { api, imageUrl, number, type Alignment, type Exam, type Lesion, type Report, type Roi, type State } from './api'

type ViewId = 'basePet' | 'currentPet' | 'baseCt' | 'currentCt'
type Layout = 'four' | 'petCompare' | 'currentPair' | 'single' | 'oneThree' | 'twoByFour'
type SideTab = 'lesions' | 'roi' | 'references' | 'assessment' | 'parameters' | 'history'
type BottomTab = 'compare' | 'report'
type Tool = 'roi' | 'pan' | 'align' | 'blood_pool' | 'liver'
type AlignView = 'basePet' | 'currentPet'
type AlignMark = { index: number; point: [number, number] }
type MprPlane = 'coronal' | 'sagittal' | 'mip'
type MprKey = 'baseCoronal' | 'baseSagittal' | 'currentCoronal' | 'currentSagittal'

const VIEW_IDS: ViewId[] = ['basePet', 'currentPet', 'baseCt', 'currentCt']
const LABELS: Record<ViewId, string> = {
  basePet: '基线 PET', currentPet: '本次 PET', baseCt: '基线 CT', currentCt: '本次 CT',
}

function examDate(exam?: Exam | null) {
  return exam?.study_datetime?.slice(0, 10) || '—'
}

function compactId(value: string) {
  return value.slice(-8).toUpperCase()
}

function Viewer(props: {
  id: ViewId; examId?: string; state: State; position: number; selected: boolean;
  onSelect: () => void; onPosition: (next: number) => void; onSeed: (index: number, point: [number, number]) => void;
  onAlignMark: (id: AlignView, mark: AlignMark) => void;
  onReferenceMark: (kind: 'blood_pool' | 'liver', mark: AlignMark) => void;
  roiImage: string | null; tool: Tool; zoom: number; pan: [number, number];
  onPan: (next: [number, number]) => void; center: number; width: number; petMax: number;
  fusion: boolean; fusionOpacity: number;
}) {
  const { id, examId, state, position, selected, onSelect, onPosition, onSeed, onAlignMark, onReferenceMark,
    roiImage, tool, zoom, pan, onPan, center, width, petMax, fusion, fusionOpacity } = props
  const modality = id.endsWith('Pet') ? 'pet' : 'ct'
  const count = examId ? state.exam_counts[examId]?.[modality] || 0 : 0
  const index = Math.round(position * Math.max(0, count - 1))
  const ref = useRef<HTMLImageElement>(null)
  const drag = useRef<{ x: number; y: number; start: [number, number] } | null>(null)
  const referenceVersion = id === 'currentPet'
    ? `${state.references?.blood_pool?.version || 0}-${state.references?.liver?.version || 0}` : '0'
  const shownModality = modality === 'ct' && fusion ? 'fusion' : modality
  const url = examId ? `${imageUrl(examId, shownModality, index, center, width, petMax)}&ref=${referenceVersion}&opacity=${fusionOpacity}` : ''
  const source = id === 'currentPet' && roiImage ? roiImage : url

  function clickImage(event: React.MouseEvent<HTMLImageElement>) {
    onSelect()
    if ((!['roi', 'align', 'blood_pool', 'liver'].includes(tool)) || !ref.current || drag.current) return
    if (tool === 'roi' && id !== 'currentPet') return
    if (tool === 'align' && id !== 'basePet' && id !== 'currentPet') return
    if ((tool === 'blood_pool' || tool === 'liver') && id !== 'currentPet') return
    const image = ref.current
    const bounds = image.getBoundingClientRect()
    const natural = image.naturalWidth / image.naturalHeight
    const frame = bounds.width / bounds.height
    const shownWidth = frame > natural ? bounds.height * natural : bounds.width
    const shownHeight = frame > natural ? bounds.height : bounds.width / natural
    const left = bounds.left + (bounds.width - shownWidth) / 2
    const top = bounds.top + (bounds.height - shownHeight) / 2
    const x = Math.floor((event.clientX - left) / shownWidth * image.naturalWidth)
    const y = Math.floor((event.clientY - top) / shownHeight * image.naturalHeight)
    if (x >= 0 && x < image.naturalWidth && y >= 0 && y < image.naturalHeight) {
      if (tool === 'align') onAlignMark(id as AlignView, { index, point: [x, y] })
      else if (tool === 'blood_pool' || tool === 'liver') onReferenceMark(tool, { index, point: [x, y] })
      else onSeed(index, [x, y])
    }
  }

  function pointerDown(event: React.PointerEvent<HTMLDivElement>) {
    onSelect()
    if (tool === 'pan') {
      drag.current = { x: event.clientX, y: event.clientY, start: pan }
      event.currentTarget.setPointerCapture(event.pointerId)
    }
  }

  function pointerMove(event: React.PointerEvent<HTMLDivElement>) {
    if (!drag.current) return
    onPan([drag.current.start[0] + event.clientX - drag.current.x,
      drag.current.start[1] + event.clientY - drag.current.y])
  }

  const moveSlice = (step: number) => onPosition(Math.min(1, Math.max(0, position + step / Math.max(1, count - 1))))

  return <section className={'viewer' + (selected ? ' viewer-selected' : '')} onClick={onSelect}
    tabIndex={0} aria-label={`${LABELS[id]}，第 ${index + 1} 层，共 ${count} 层`}
    onKeyDown={(event) => {
      if (event.key === 'ArrowUp' || event.key === 'ArrowRight') { event.preventDefault(); moveSlice(1) }
      if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') { event.preventDefault(); moveSlice(-1) }
    }}>
    <div className="viewer-image" onPointerDown={pointerDown} onPointerMove={pointerMove}
      onPointerUp={() => { drag.current = null }}
      onWheel={(event) => { event.preventDefault(); moveSlice(Math.sign(event.deltaY)) }}>
      {examId ? <img ref={ref} src={source} draggable={false} onClick={clickImage} alt={`${LABELS[id]} 第 ${index + 1} 层`}
        style={{ transform: `translate(${pan[0]}px, ${pan[1]}px) scale(${zoom})`, cursor: tool === 'pan' ? 'grab' : (tool === 'align' && id.endsWith('Pet')) || (tool !== 'align' && id === 'currentPet') ? 'crosshair' : 'default' }} />
        : <span className="empty-view">未载入基线检查</span>}
      <div className="corner top-left"><strong>{fusion && modality === 'ct' ? LABELS[id].replace('CT', 'PET/CT') : LABELS[id]}</strong><br />{examDate(id.startsWith('base') ? state.prior : state.exam)}<br />{fusion && modality === 'ct' ? 'PET/CT' : modality.toUpperCase()} · Axial</div>
      <div className="corner top-right">{index + 1} / {count}<br />{modality === 'ct' ? `W ${width} · L ${center}` : '显示强度可调'}</div>
      <div className="corner bottom-left">{state.exam.is_synthetic ? '示意影像' : '本机导入'}</div>
      <div className="corner bottom-right">{modality === 'pet' ? 'PET' : 'CT'} · {selected ? '当前视口' : '点击激活'}</div>
    </div>
  </section>
}

function MprViewer(props: {
  examId?: string; phase: 'base' | 'current'; plane: MprPlane; state: State;
  position: number; onPosition: (next: number) => void;
  center: number; width: number; petMax: number;
}) {
  const { examId, phase, plane, state, position, onPosition, center, width, petMax } = props
  const shape = examId ? state.exam_shapes[examId]?.pet : undefined
  const count = plane === 'coronal' ? shape?.[0] || 0 : plane === 'sagittal' ? shape?.[1] || 0 : 1
  const index = plane === 'mip' ? 0 : Math.round(position * Math.max(0, count - 1))
  const name = plane === 'mip' ? 'MIP' : plane === 'coronal' ? '冠状' : '矢状'
  const move = (step: number) => { if (plane !== 'mip') onPosition(Math.min(1, Math.max(0, position + step / Math.max(1, count - 1)))) }
  const src = examId ? `${imageUrl(examId, 'pet', index, center, width, petMax)}&plane=${plane}` : ''
  return <section className="viewer mpr-viewer" tabIndex={0} aria-label={`${phase === 'base' ? '基线' : '本次'} PET ${name}`}
    onKeyDown={event => { if (event.key === 'ArrowUp' || event.key === 'ArrowRight') { event.preventDefault(); move(1) } if (event.key === 'ArrowDown' || event.key === 'ArrowLeft') { event.preventDefault(); move(-1) } }}>
    <div className="viewer-image" onWheel={event => { event.preventDefault(); move(Math.sign(event.deltaY)) }}>
      {examId ? <img src={src} draggable={false} alt={`${phase === 'base' ? '基线' : '本次'} PET ${name}`} /> : <span className="empty-view">未载入基线检查</span>}
      <div className="corner top-left"><strong>{phase === 'base' ? '基线' : '本次'} PET · {name}</strong><br />{examDate(phase === 'base' ? state.prior : state.exam)}</div>
      {plane !== 'mip' && <div className="corner top-right">{index + 1} / {count}</div>}
      <div className="corner bottom-left">{state.exam.is_synthetic ? '示意影像' : '本机导入'}</div>
    </div>
  </section>
}

function App() {
  const [state, setState] = useState<State | null>(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [layout, setLayout] = useState<Layout>('four')
  const [sideTab, setSideTab] = useState<SideTab>('lesions')
  const [bottomTab, setBottomTab] = useState<BottomTab>('compare')
  const [tool, setTool] = useState<Tool>('roi')
  const [sync, setSync] = useState(true)
  const [alignment, setAlignment] = useState<Alignment | null>(null)
  const [alignMarks, setAlignMarks] = useState<Record<AlignView, AlignMark | null>>({ basePet: null, currentPet: null })
  const [activeView, setActiveView] = useState<ViewId>('currentPet')
  const [positions, setPositions] = useState<Record<ViewId, number>>({ basePet: .5, currentPet: .5, baseCt: .5, currentCt: .5 })
  const [mprPositions, setMprPositions] = useState<Record<MprKey, number>>({ baseCoronal: .5, baseSagittal: .5, currentCoronal: .5, currentSagittal: .5 })
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [priorLesionId, setPriorLesionId] = useState('')
  const [seed, setSeed] = useState<[number, number] | null>(null)
  const [seedIndex, setSeedIndex] = useState<number | null>(null)
  const [fraction, setFraction] = useState(.41)
  const [label, setLabel] = useState('')
  const [roiImage, setRoiImage] = useState<string | null>(null)
  const [pixels, setPixels] = useState(0)
  const [voiVoxels, setVoiVoxels] = useState(0)
  const [history, setHistory] = useState<Record<string, unknown>[]>([])
  const [report, setReport] = useState<Report | null>(null)
  const [description, setDescription] = useState('')
  const [reviewer, setReviewer] = useState('')
  const [score, setScore] = useState('')
  const [category, setCategory] = useState('')
  const [assessmentReason, setAssessmentReason] = useState('')
  const [manualSourceA, setManualSourceA] = useState('')
  const [manualSourceB, setManualSourceB] = useState('')
  const [manualA, setManualA] = useState<Record<string, string>>({})
  const [manualB, setManualB] = useState<Record<string, string>>({})
  const [revokeReason, setRevokeReason] = useState('')
  const [zoom, setZoom] = useState(1)
  const [pans, setPans] = useState<Record<ViewId, [number, number]>>({ basePet: [0, 0], currentPet: [0, 0], baseCt: [0, 0], currentCt: [0, 0] })
  const [center, setCenter] = useState(40)
  const [width, setWidth] = useState(400)
  const [petMax, setPetMax] = useState(12000)
  const [fusion, setFusion] = useState(false)
  const [fusionOpacity, setFusionOpacity] = useState(.45)
  const importInput = useRef<HTMLInputElement>(null)

  const run = useCallback(async (task: () => Promise<void>) => {
    setBusy(true); setError('')
    try { await task() } catch (cause) { setError(cause instanceof Error ? cause.message : '操作失败') }
    finally { setBusy(false) }
  }, [])

  const refresh = useCallback(async (examId?: string) => {
    const next = await api<State>('/state' + (examId ? `?exam_id=${encodeURIComponent(examId)}` : ''))
    setState(next)
    setSelectedId(current => next.lesions.some(l => l.lesion_id === current) ? current : next.lesions[0]?.lesion_id || null)
    return next
  }, [])

  useEffect(() => { void run(async () => {
    try { await refresh() } catch { const result = await api<{ exam_id: string }>('/demo', {}); await refresh(result.exam_id) }
  }) }, [refresh, run])

  const selectedLesion = state?.lesions.find(l => l.lesion_id === selectedId)
  const selectedMeasure = state?.measurements.find(m => m.lesion_id === selectedId)
  const selectedAssessment = selectedId ? state?.assessments[selectedId] : undefined
  const currentExamId = state?.exam.exam_id
  const baseExamId = state?.prior?.exam_id
  const currentPetIndex = state ? Math.round(positions.currentPet * (state.pet_count - 1)) : 0
  const activeAlignment = alignment?.base_exam_id === baseExamId && alignment?.current_exam_id === currentExamId ? alignment : null

  function updatePosition(id: ViewId, next: number) {
    setPositions(previous => {
      if (!sync) return { ...previous, [id]: next }
      if (!activeAlignment) return Object.fromEntries(VIEW_IDS.map(key => [key, next])) as Record<ViewId, number>
      const source = activeAlignment.slice_locations[id]
      const sourceIndex = Math.round(next * Math.max(0, source.length - 1))
      const sourceLocation = source[sourceIndex]
      return Object.fromEntries(VIEW_IDS.map(key => {
        const target = activeAlignment.slice_locations[key]
        const shift = id.startsWith('base') === key.startsWith('base') ? 0
          : key.startsWith('base') ? -activeAlignment.offset_along_normal_mm : activeAlignment.offset_along_normal_mm
        const wanted = sourceLocation + shift
        const closest = target.reduce((best, value, index) => Math.abs(value - wanted) < Math.abs(target[best] - wanted) ? index : best, 0)
        return [key, closest / Math.max(1, target.length - 1)]
      })) as Record<ViewId, number>
    })
  }

  useEffect(() => {
    if (!alignMarks.basePet || !alignMarks.currentPet || !currentExamId || !baseExamId) return
    let cancelled = false
    void api<Alignment>('/align', { exam_id: currentExamId, base: alignMarks.basePet, current: alignMarks.currentPet })
      .then(result => {
        if (cancelled) return
        setAlignment(result); setTool('roi'); setSync(true); setError('')
      })
      .catch(cause => { if (!cancelled) setError(cause instanceof Error ? cause.message : '单点对齐失败') })
    return () => { cancelled = true }
  }, [alignMarks.basePet, alignMarks.currentPet, currentExamId, baseExamId])

  useEffect(() => {
    if (!state || !seed || seedIndex == null) return
    const timer = window.setTimeout(() => {
      void api<{ image: string; pixels: number; voxel_count: number }>('/roi/preview', {
        exam_id: state.exam.exam_id, index: seedIndex, display_index: currentPetIndex, seed, fraction,
      }).then(result => { setRoiImage(result.image); setPixels(result.pixels); setVoiVoxels(result.voxel_count) })
        .catch(cause => setError(cause instanceof Error ? cause.message : 'ROI 预览失败'))
    }, 100)
    return () => window.clearTimeout(timer)
  }, [state?.exam.exam_id, currentPetIndex, seedIndex, seed?.[0], seed?.[1], fraction])

  async function loadRoi(lesion: Lesion) {
    if (!currentExamId) return
    setSelectedId(lesion.lesion_id); setLabel(lesion.label); setSideTab('roi')
    const result = await api<Roi>(`/roi?exam_id=${encodeURIComponent(currentExamId)}&lesion_id=${encodeURIComponent(lesion.lesion_id)}`)
    setSeed(result.seed); setSeedIndex(result.index); setFraction(result.fraction); setRoiImage(result.image)
    updatePosition('currentPet', result.index / Math.max(1, (state?.pet_count || 1) - 1))
  }

  async function saveRoi() {
    if (!state || !seed || seedIndex == null || !label.trim()) throw new Error('请先在本次 PET 图像点选病灶，并填写部位')
    const result = await api<{ lesion_id: string; state: State }>('/roi', {
      exam_id: currentExamId, index: seedIndex, seed, fraction, label: label.trim(), lesion_id: selectedId,
    })
    setState(result.state); setSelectedId(result.lesion_id); setRoiImage(null); setSeed(null); setSeedIndex(null)
  }

  async function editValue(field: 'suv_max' | 'longest_diameter_mm') {
    if (!selectedId || !currentExamId) return
    const previous = field === 'suv_max' ? selectedMeasure?.suv_max : selectedMeasure?.longest_diameter_mm
    const raw = window.prompt(`修订${field === 'suv_max' ? 'SUVmax' : 'CT 最长径 (mm)'}；当前值 ${number(previous)}`, previous == null ? '' : String(previous))
    if (raw === null) return
    const value = Number(raw)
    if (!raw.trim() || !Number.isFinite(value)) throw new Error('请输入有效数字')
    const note = window.prompt('填写修改依据（会保存到数值留痕）')
    if (note === null) return
    setState(await api<State>('/value', { exam_id: currentExamId, lesion_id: selectedId, field, value, note }))
  }

  async function showHistory() {
    setSideTab('history')
    if (selectedId && currentExamId) setHistory(await api<Record<string, unknown>[]>(`/history?exam_id=${encodeURIComponent(currentExamId)}&lesion_id=${encodeURIComponent(selectedId)}`))
  }

  async function showReport() {
    if (!currentExamId) return
    setBottomTab('report')
    const result = await api<Report>(`/report?exam_id=${encodeURIComponent(currentExamId)}`)
    setReport(result); setDescription(result.description)
  }

  async function copyForRis() {
    if (!currentExamId || !report || description !== report.description) throw new Error('请先保存报告草稿')
    const response = await fetch(`/api/report/export?exam_id=${encodeURIComponent(currentExamId)}`)
    if (!response.ok) {
      const problem = await response.json().catch(() => ({}))
      throw new Error(problem.error || '报告导出失败')
    }
    await navigator.clipboard.writeText(await response.text())
    setError('报告内容已复制，可粘贴到 RIS')
  }

  async function placeReference(kind: 'blood_pool' | 'liver', mark: AlignMark) {
    if (!currentExamId) return
    await api('/reference', { exam_id: currentExamId, kind, ...mark })
    setState(await api<State>(`/state?exam_id=${encodeURIComponent(currentExamId)}`))
    setTool('roi')
  }

  async function confirmReference(kind: 'blood_pool' | 'liver', version: number) {
    if (!currentExamId || !reviewer.trim()) throw new Error('请先填写确认人，并核对 PET/CT 内参位置')
    await api('/reference/confirm', { exam_id: currentExamId, kind, version, reviewer: reviewer.trim() })
    setState(await api<State>(`/state?exam_id=${encodeURIComponent(currentExamId)}`))
  }

  async function confirmAssessment() {
    if (!currentExamId || !selectedId || !selectedAssessment) throw new Error('请先选择本次病灶')
    if (!reviewer.trim() || !assessmentReason.trim()) throw new Error('请填写确认人和判读依据')
    await api('/assessment/confirm', {
      exam_id: currentExamId, lesion_id: selectedId, fingerprint: selectedAssessment.fingerprint,
      score, category, reviewer: reviewer.trim(), reason: assessmentReason.trim(),
    })
    setState(await api<State>(`/state?exam_id=${encodeURIComponent(currentExamId)}`))
  }

  async function saveManualParams() {
    if (!currentExamId) return
    const values = (source: Record<string, string>) => Object.fromEntries(
      Object.entries(source).filter(([, value]) => value.trim()).map(([key, value]) => [key,
        ['patient_weight_kg', 'dose_bq', 'half_life_s'].includes(key) ? Number(value) : value.trim()]))
    const response = await api<{ state: State }>('/manual-params', {
      exam_id: currentExamId, reviewer: reviewer.trim(),
      source_a: { name: manualSourceA.trim(), values: values(manualA) },
      source_b: { name: manualSourceB.trim(), values: values(manualB) },
    })
    setState(response.state)
  }

  async function revokeManualParams() {
    if (!currentExamId) return
    const response = await api<{ state: State }>('/manual-params/revoke', {
      exam_id: currentExamId, reviewer: reviewer.trim(), reason: revokeReason.trim(),
    })
    setState(response.state)
    setRevokeReason('')
  }

  async function uploadDirectory(files: FileList | null) {
    if (!files?.length) return
    const form = new FormData()
    for (const file of Array.from(files)) form.append('files', file, file.webkitRelativePath || file.name)
    const response = await fetch('/api/upload', { method: 'POST', body: form })
    const result = await response.json()
    if (!response.ok) throw new Error(result.error || '影像导入失败')
    await refresh(result.exam_id)
    setSeed(null); setRoiImage(null); setAlignment(null); setAlignMarks({ basePet: null, currentPet: null })
  }

  const views = useMemo(() => {
    if (layout === 'petCompare') return ['basePet', 'currentPet'] as ViewId[]
    if (layout === 'currentPair') return ['currentPet', 'currentCt'] as ViewId[]
    if (layout === 'single') return [activeView]
    return VIEW_IDS
  }, [layout, activeView])

  const axialViewer = (id: ViewId) => <Viewer key={id} id={id} state={state!}
    examId={id.startsWith('base') ? baseExamId : currentExamId}
    position={positions[id]} selected={activeView === id} onSelect={() => setActiveView(id)}
    onPosition={next => updatePosition(id, next)}
    onAlignMark={(view, mark) => setAlignMarks(previous => ({ ...previous, [view]: mark }))}
    onReferenceMark={(kind, mark) => void run(() => placeReference(kind, mark))}
    onSeed={(index, point) => { setSeed(point); setSeedIndex(index); setRoiImage(null); setSelectedId(null); setLabel(''); setSideTab('roi') }}
    roiImage={id === 'currentPet' ? roiImage : null} tool={tool} zoom={zoom} pan={pans[id]}
    onPan={next => setPans(previous => ({ ...previous, [id]: next }))}
    center={center} width={width} petMax={petMax} fusion={fusion} fusionOpacity={fusionOpacity} />
  const mprViewer = (phase: 'base' | 'current', plane: MprPlane) => {
    const key = `${phase}${plane[0].toUpperCase()}${plane.slice(1)}` as MprKey
    return <MprViewer key={key} phase={phase} plane={plane} state={state!}
      examId={phase === 'base' ? baseExamId : currentExamId}
      position={plane === 'mip' ? 0 : mprPositions[key]}
      onPosition={next => { if (plane !== 'mip') setMprPositions(previous => ({ ...previous, [key]: next })) }}
      center={center} width={width} petMax={petMax} />
  }

  if (!state) return <main className="loading">{error || '正在载入示意双期病例…'}</main>

  return <div className="app-shell">
    <header className="topbar">
      <div className="app-title">淋巴瘤 PET 随访</div>
      <div className="patient-meta"><span>患者 <b className="mono">{compactId(state.exam.patient_pseudo_id)}</b></span><span>检查类型 PET/CT</span><span>本次 <b className="mono">{examDate(state.exam)}</b></span></div>
      <div className="exam-switch"><label>检查 <select value={state.exam.exam_id} onChange={e => void run(async () => { await refresh(e.target.value); setSeed(null); setRoiImage(null); setAlignment(null); setAlignMarks({ basePet: null, currentPet: null }) })}>
        {state.exams.map(exam => <option key={exam.exam_id} value={exam.exam_id}>{examDate(exam)}</option>)}
      </select></label><label>基线 <select value={state.exam.prior_exam_id || ''} onChange={e => void run(async () => {
        setState(await api<State>('/prior', { exam_id: currentExamId, prior_exam_id: e.target.value || null }))
        setAlignment(null); setAlignMarks({ basePet: null, currentPet: null })
      })}><option value="">未关联</option>{state.candidates.map(exam => <option key={exam.exam_id} value={exam.exam_id}>{examDate(exam)}</option>)}</select></label></div>
    </header>

    <nav className="toolbar" aria-label="图像工具">
      <input ref={importInput} type="file" multiple {...{ webkitdirectory: '' }} hidden onChange={event => {
        const files = event.target.files
        void run(() => uploadDirectory(files))
        event.target.value = ''
      }} />
      <button onClick={() => importInput.current?.click()}><FolderOpen />导入</button>
      <button onClick={() => void run(async () => { const result = await api<{ exam_id: string }>('/demo', {}); await refresh(result.exam_id); setAlignment(null); setAlignMarks({ basePet: null, currentPet: null }) })}>示意病例</button>
      <span className="toolbar-divider" />
      <label className="toolbar-select"><Columns2 />布局 <select aria-label="图像布局" value={layout} onChange={e => setLayout(e.target.value as Layout)}>
        <option value="four">双期四格</option><option value="petCompare">双期双格</option><option value="currentPair">本次双格</option><option value="single">单视口</option><option value="oneThree">单期 1＋3</option><option value="twoByFour">双期 2×4</option>
      </select></label>
      <button className={sync ? 'active' : ''} onClick={() => setSync(!sync)} title={activeAlignment ? '基于两期 PET 人工标志点的空间翻层' : '按层数比例联动，不代表解剖配准'}><Link2 />{activeAlignment ? '空间联动' : '比例联动'}</button>
      <button className={tool === 'align' ? 'active' : ''} disabled={!baseExamId} onClick={() => { setTool('align'); setSync(false); setAlignMarks({ basePet: null, currentPet: null }); setAlignment(null) }} title="分别在两期 PET 的同一骨性标志上点击一次">单点对齐</button>
      <span className="toolbar-divider" />
      <button className={tool === 'roi' ? 'active' : ''} onClick={() => { setTool('roi'); setActiveView('currentPet') }}><MousePointer2 />ROI 种子</button>
      <button className={tool === 'pan' ? 'active' : ''} onClick={() => setTool('pan')}>平移</button>
      <button aria-label="放大" onClick={() => setZoom(Math.min(4, zoom + .25))}><ZoomIn /></button>
      <button aria-label="缩小" onClick={() => setZoom(Math.max(1, zoom - .25))}><ZoomOut /></button>
      <button title="复位图像显示" onClick={() => { setZoom(1); setPans({ basePet: [0, 0], currentPet: [0, 0], baseCt: [0, 0], currentCt: [0, 0] }); setCenter(40); setWidth(400); setPetMax(12000) }}><RotateCcw />复位</button>
      <span className="toolbar-divider" />
      <label className="compact-field">CT窗位 <input type="number" value={center} onChange={e => setCenter(Number(e.target.value))} /></label>
      <label className="compact-field">窗宽 <input type="number" min="1" value={width} onChange={e => setWidth(Math.max(1, Number(e.target.value)))} /></label>
      <label className="compact-field">PET上限 <input type="number" min="1" value={petMax} onChange={e => setPetMax(Math.max(1, Number(e.target.value)))} /></label>
      <button className={fusion ? 'active' : ''} onClick={() => setFusion(!fusion)} title="按同一 DICOM 空间坐标将 PET 叠加到 CT；缺少空间配准会拒绝显示">PET/CT 融合</button>
      {fusion && <label className="compact-field">PET 透明度 <input aria-label="PET 融合透明度" type="range" min="0" max="100" value={Math.round(fusionOpacity * 100)} onChange={e => setFusionOpacity(Number(e.target.value) / 100)} />{Math.round(fusionOpacity * 100)}%</label>}
      <span className="toolbar-spacer" />
      <button onClick={() => void run(showHistory)}><History />留痕</button>
      <button onClick={() => void run(showReport)}><FileText />报告草稿</button>
    </nav>

    {error && <div className="message" role="alert"><span>{error}</span><button onClick={() => setError('')}>关闭</button></div>}

    <div className="work-area">
      <div className={`view-grid layout-${layout}`}>
        {layout === 'oneThree' ? <>{mprViewer('current', 'mip')}{axialViewer('currentPet')}{mprViewer('current', 'coronal')}{mprViewer('current', 'sagittal')}</>
          : layout === 'twoByFour' ? <>{mprViewer('base', 'mip')}{axialViewer('basePet')}{mprViewer('base', 'coronal')}{mprViewer('base', 'sagittal')}{mprViewer('current', 'mip')}{axialViewer('currentPet')}{mprViewer('current', 'coronal')}{mprViewer('current', 'sagittal')}</>
            : views.map(axialViewer)}
      </div>

      <aside className="side-pane">
        <div className="tabs"><button className={sideTab === 'lesions' ? 'selected' : ''} onClick={() => setSideTab('lesions')}>病灶</button><button className={sideTab === 'roi' ? 'selected' : ''} onClick={() => setSideTab('roi')}>ROI量测</button><button className={sideTab === 'references' ? 'selected' : ''} onClick={() => setSideTab('references')}>内参</button><button className={sideTab === 'assessment' ? 'selected' : ''} onClick={() => setSideTab('assessment')}>判读</button><button className={sideTab === 'parameters' ? 'selected' : ''} onClick={() => setSideTab('parameters')}>参数</button><button className={sideTab === 'history' ? 'selected' : ''} onClick={() => void run(showHistory)}>留痕</button></div>
        {sideTab === 'lesions' && <div className="side-content">
          <div className="section-head"><strong>本次病灶</strong><button onClick={() => { setSelectedId(null); setSeed(null); setRoiImage(null); setLabel(''); setSideTab('roi'); setActiveView('currentPet') }}>＋ 新建 ROI</button></div>
          <table className="dense-table lesion-table"><thead><tr><th>部位</th><th>SUVmax</th><th>最长径</th><th>状态</th></tr></thead><tbody>
            {state.lesions.map(lesion => { const measure = state.measurements.find(m => m.lesion_id === lesion.lesion_id); return <tr key={lesion.lesion_id} className={selectedId === lesion.lesion_id ? 'selected-row' : ''} onClick={() => void run(() => loadRoi(lesion))}><td title={lesion.label}>{lesion.label}</td><td className="mono">{number(measure?.suv_max)}</td><td className="mono">{number(measure?.longest_diameter_mm, 1)}</td><td className={measure?.state === 'needs_review' ? 'status-review' : ''}>{measure?.state === 'needs_review' ? '待复核' : '待确认'}</td></tr> })}
          </tbody></table>
          {!state.lesions.length && <p className="empty-hint">在本次 PET 图像点选高摄取区域，生成第一项 ROI。</p>}
          <div className="section-head separated"><strong>跨期关联</strong><span>人工确认</span></div>
          <label className="field-label">本次病灶 <span>{selectedLesion?.label || '未选择'}</span></label>
          <label className="field-label">基线病灶 <select value={priorLesionId} onChange={e => setPriorLesionId(e.target.value)}><option value="">选择基线病灶</option>{state.prior_lesions.map(l => <option key={l.lesion_id} value={l.lesion_id}>{l.label}</option>)}</select></label>
          <div className="inline-actions"><button disabled={!selectedId || !priorLesionId || !baseExamId} onClick={() => void run(async () => { setState(await api<State>('/pair', { exam_id: currentExamId, lesion_id: selectedId, prior_lesion_id: priorLesionId })); setBottomTab('compare') })}>指定配对</button><button disabled={!selectedId} onClick={() => void run(async () => { setState(await api<State>('/pair', { exam_id: currentExamId, lesion_id: selectedId, prior_lesion_id: null })) })}>解除配对</button></div>
        </div>}
        {sideTab === 'roi' && <div className="side-content">
          <div className="section-head"><strong>{selectedLesion ? '编辑 ROI' : '新建 ROI'}</strong><span>本次 PET</span></div>
          <label className="field-label">病灶部位 <input value={label} onChange={e => setLabel(e.target.value)} placeholder="例如：左锁骨上淋巴结" /></label>
          <label className="field-label">种子点 <span className="mono">{seed ? `${seed[0]}, ${seed[1]}` : '点击 PET 图像'}</span></label>
          <label className="field-label">阈值 <span className="mono">{Math.round(fraction * 100)}% 局部 SUVmax</span></label>
          <input className="threshold" type="range" min="20" max="95" value={Math.round(fraction * 100)} onChange={e => setFraction(Number(e.target.value) / 100)} />
          <p className="muted-note">三维六连通 VOI · 预览 {voiVoxels} 体素，当前层 {pixels} 像素。搜索范围 30 mm；请逐层核对轮廓及生理摄取。</p>
          <button className="primary-action" disabled={busy || !seed} onClick={() => void run(saveRoi)}><Save />保存 ROI 与量测</button>
          {selectedId && <a className="button-link" href={`/api/key-image/export?exam_id=${encodeURIComponent(currentExamId || '')}&lesion_id=${encodeURIComponent(selectedId)}`} download>导出 DICOM Key Image</a>}
          <div className="section-head separated"><strong>量测</strong><span>{selectedMeasure?.state === 'needs_review' ? '待复核' : '待确认'}</span></div>
          <div className="measure-line"><span>SUVmax</span><b className="mono">{number(selectedMeasure?.suv_max)}</b><button disabled={!selectedId} onClick={() => void run(() => editValue('suv_max'))}>修订</button></div>
          <div className="measure-line"><span>CT 最长径</span><b className="mono">{number(selectedMeasure?.longest_diameter_mm, 1)} <small>mm</small></b><button disabled={!selectedId} onClick={() => void run(() => editValue('longest_diameter_mm'))}>修订</button></div>
          <div className="measure-line"><span>CT 同层长 / 短径</span><b className="mono">{number(selectedMeasure?.ct_long_mm, 1)} / {number(selectedMeasure?.ct_short_mm, 1)} <small>mm</small></b></div>
          <div className="measure-line"><span>CT SPD 估计</span><b className="mono">{number(selectedMeasure?.ct_spd_mm2, 1)} <small>mm²</small></b></div>
          {selectedMeasure?.ct_dimensions_note && <p className="muted-note">{selectedMeasure.ct_dimensions_note}</p>}
          <p className="muted-note">数值来源、人工修改和复核原因可在「留痕」查看。</p>
        </div>}
        {sideTab === 'references' && <div className="side-content">
          <div className="section-head"><strong>生理内参</strong><span>本次 PET · 人工放置</span></div>
          <p className="muted-note">选择工具后，在降主动脉血池或肝右叶实质点击中心点。避开血管壁、病灶及器官边缘，并在 PET/CT 上核对位置。</p>
          <div className="inline-actions"><button className={tool === 'blood_pool' ? 'active' : ''} onClick={() => { setTool('blood_pool'); setActiveView('currentPet') }}>血池柱形 VOI</button><button className={tool === 'liver' ? 'active' : ''} onClick={() => { setTool('liver'); setActiveView('currentPet') }}>肝脏球形 VOI</button></div>
          <label className="field-label">确认人 <input value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="填写姓名或工号" /></label>
          {(['blood_pool', 'liver'] as const).map(kind => { const item = state.references?.[kind]; return <div key={kind} className="reference-group">
            <div className="section-head separated"><strong>{kind === 'blood_pool' ? '纵隔血池' : '肝脏背景'}</strong><span>{item ? `第 ${item.version} 版 · ${item.placement_confirmed ? '已确认' : '待核对'}` : '未放置'}</span></div>
            <div className="measure-line"><span>SUVmax</span><b className="mono">{number(item?.suv_max)}</b></div>
            <div className="measure-line"><span>SUVmean</span><b className="mono">{number(item?.suv_mean)}</b></div>
            {item && <p className="muted-note">{item.voxel_count} 像素 · 原始浓度 {number(item.raw_mean)} {item.raw_units}{item.note ? ` · ${item.note}` : ''}</p>}
            {item && !item.placement_confirmed && <div className="inline-actions"><button disabled={busy || item.suv_mean == null} onClick={() => void run(() => confirmReference(kind, item.version))}>核对位置后确认</button></div>}
            {item?.placement_confirmed && <p className="muted-note">确认人 {item.confirmed_by} · {item.confirmed_at?.slice(0, 19)}</p>}
          </div> })}
        </div>}
        {sideTab === 'assessment' && <div className="side-content">
          <div className="section-head"><strong>辅助判读 · 医生确认</strong><span>{selectedLesion?.label || '未选择病灶'}</span></div>
          {selectedAssessment ? <>
            <p className="muted-note">系统提示：{selectedAssessment.suggestion}</p>
            <div className="measure-line"><span>本次 SUVmax</span><b className="mono">{number(selectedAssessment.evidence.current_suv_max)}</b></div>
            <div className="measure-line"><span>ΔSUVmax</span><b className="mono">{selectedAssessment.evidence.delta_suv_pct == null ? '—' : `${number(selectedAssessment.evidence.delta_suv_pct, 1)}%`}</b></div>
            {selectedAssessment.confirmed && <p className="muted-note">{selectedAssessment.stale ? '来源已变化，请重新判读' : '已确认'}：Deauville {selectedAssessment.confirmed.score} · Lugano {selectedAssessment.confirmed.category} · {selectedAssessment.confirmed.reviewer} · 第 {selectedAssessment.confirmed.version} 版</p>}
            <label className="field-label">Deauville <select value={score} onChange={e => setScore(e.target.value)}><option value="">医生选择</option>{['1', '2', '3', '4', '5', 'X'].map(value => <option key={value} value={value}>{value}</option>)}</select></label>
            <label className="field-label">Lugano <select value={category} onChange={e => setCategory(e.target.value)}><option value="">医生选择</option><option value="CMR">CMR</option><option value="PMR">PMR</option><option value="NMR">NMR</option><option value="PMD">PMD</option><option value="indeterminate">待定</option></select></label>
            <label className="field-label">确认人 <input value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="姓名或工号" /></label>
            <label className="field-label">判读依据 <input value={assessmentReason} onChange={e => setAssessmentReason(e.target.value)} placeholder="记录影像与临床判断依据" /></label>
            <div className="inline-actions"><button disabled={busy || !score || !category} onClick={() => void run(confirmAssessment)}>保存医生确认</button></div>
            <p className="muted-note">提示仅按已确认内参的摄取范围分层；1/2、4/5 和 X 需要医生结合影像判断。确认结果随来源变化标记为过期。</p>
          </> : <p className="empty-hint">先在「病灶」列表选择本次病灶。</p>}
        </div>}
        {sideTab === 'parameters' && <div className="side-content">
          <div className="section-head"><strong>定量参数补录</strong><span>{state.exam.manual_input ? `[Manual Input] 第 ${state.exam.manual_input.version} 版` : '无人工补录'}</span></div>
          <p className="muted-note">仅补缺失的 BQML 定量参数。两个独立来源需分别输入同一数值；与 DICOM 冲突时拒绝保存。缺少衰减校正或原始单位时仍不能输出 SUV。</p>
          <label className="field-label">核对人 <input value={reviewer} onChange={e => setReviewer(e.target.value)} placeholder="姓名或工号" /></label>
          <label className="field-label">来源 A <input value={manualSourceA} onChange={e => setManualSourceA(e.target.value)} placeholder="如注射记录" /></label>
          <label className="field-label">来源 B <input value={manualSourceB} onChange={e => setManualSourceB(e.target.value)} placeholder="如扫描日志" /></label>
          <div className="manual-grid manual-heading"><span>缺失字段</span><span>来源 A 数值</span><span>来源 B 数值</span></div>
          {([['patient_weight_kg', '体重 kg'], ['dose_bq', '注射剂量 Bq'], ['half_life_s', '半衰期 s'], ['injection_datetime', '注射时间'], ['acquisition_datetime', '采集时间']] as const).map(([key, label]) => <div key={key} className="manual-grid manual-row"><span>{label}</span><input value={manualA[key] || ''} onChange={e => setManualA(previous => ({ ...previous, [key]: e.target.value }))} placeholder={key.endsWith('datetime') ? 'YYYYMMDDHHMMSS+0800' : '仅缺失时填写'} /><input value={manualB[key] || ''} onChange={e => setManualB(previous => ({ ...previous, [key]: e.target.value }))} placeholder="再次输入" /></div>)}
          <div className="inline-actions"><button disabled={busy} onClick={() => void run(saveManualParams)}>双来源核对并保存</button></div>
          {state.exam.manual_input && <p className="muted-note">最近记录：{state.exam.manual_input.source_a} + {state.exam.manual_input.source_b} · {state.exam.manual_input.reviewer}。报告会标注 [Manual Input]。</p>}
          {state.exam.manual_input && <><label className="field-label">撤销原因 <input value={revokeReason} onChange={e => setRevokeReason(e.target.value)} placeholder="填写撤销依据" /></label><div className="inline-actions"><button disabled={busy || !reviewer.trim() || !revokeReason.trim()} onClick={() => void run(revokeManualParams)}>撤销本次补录</button></div></>}
        </div>}
        {sideTab === 'history' && <div className="side-content"><div className="section-head"><strong>数值留痕</strong><span>{selectedLesion?.label || '未选择病灶'}</span></div>{history.length ? history.map((item, index) => <div key={index} className="history-row"><b>{String(item.field || '量测')}</b><span className="mono">{String(item.value ?? '—')}</span><small>{String(item.actor || '')} · {String(item.at || '').slice(0, 19)}</small><p>{String(item.note || '')}</p></div>) : <p className="empty-hint">选中病灶后查看其量测记录。</p>}</div>}
      </aside>
    </div>

    <div className={'bottom-pane' + (bottomTab === 'report' ? ' report-open' : '')}>
      <div className="tabs"><button className={bottomTab === 'compare' ? 'selected' : ''} onClick={() => setBottomTab('compare')}>纵向对照</button><button className={bottomTab === 'report' ? 'selected' : ''} onClick={() => void run(showReport)}>报告草稿</button><span className="tab-detail">数值差值为本次减基线 · 病灶对应需人工确认</span></div>
      {bottomTab === 'compare' ? <div className="table-scroll"><table className="dense-table compare-table"><thead><tr><th>本次病灶</th><th>基线病灶</th><th>基线 SUVmax</th><th>本次 SUVmax</th><th>ΔSUVmax</th><th>ΔSUVmax %</th><th>基线 SPD</th><th>本次 SPD</th><th>ΔSPD %</th><th>量测状态</th></tr></thead><tbody>{state.rows.map((row, index) => <tr key={`${row.lesion_id}-${row.prior_lesion_id}-${index}`} className={row.lesion_id === selectedId ? 'selected-row' : ''} onClick={() => row.lesion_id && setSelectedId(row.lesion_id)}><td>{row.label}</td><td>{row.prior_label || '未配对'}</td><td className="mono">{number(row.prior_suv)}</td><td className="mono">{number(row.current_suv)}</td><td className="mono">{number(row.delta_suv)}</td><td className="mono">{row.delta_suv_pct == null ? '—' : number(row.delta_suv_pct, 1) + '%'}</td><td className="mono">{number(row.prior_spd, 1)}</td><td className="mono">{number(row.current_spd, 1)}</td><td className="mono">{row.delta_spd_pct == null ? '—' : number(row.delta_spd_pct, 1) + '%'}</td><td className={row.status === 'needs_review' ? 'status-review' : ''}>{row.status === 'needs_review' ? '待复核' : '待确认'}</td></tr>)}</tbody></table>{!state.rows.length && <p className="empty-hint">保存 ROI 后，这里显示跨期病灶与量测对照。</p>}</div>
        : <div className="report-pane"><div className="generated-report"><strong>自动生成的描述性对照</strong><pre>{report?.generated || '正在载入…'}</pre>{report?.confirmed_appendix && <><strong>医生已确认判读</strong><pre>{report.confirmed_appendix}</pre></>}</div><div className="report-editor"><label>补充描述（人工编辑）<textarea value={description} onChange={e => setDescription(e.target.value)} placeholder="只记录影像所见，不填写自动诊断结论。" /></label><div className="inline-actions"><button disabled={!report} onClick={() => void run(async () => { const next = await api<Report>('/report', { exam_id: currentExamId, description, regenerate: true }); setReport(next) })}><SlidersHorizontal />重生成并保存</button><button disabled={!report} onClick={() => void run(async () => { const next = await api<Report>('/report', { exam_id: currentExamId, description }); setReport(next) })}><Save />保存</button>{report && description === report.description ? <><a className="button-link" href={`/api/report/export?exam_id=${encodeURIComponent(currentExamId || '')}`} download><Maximize2 />导出草稿</a><button onClick={() => void run(copyForRis)}>复制到 RIS</button></> : <button disabled>先保存后导出</button>}</div></div></div>}
    </div>

    <footer className="statusbar"><span>原型·不可用于临床诊疗决策</span><span>{state.exam.is_synthetic ? '示意数据' : '本机数据'}</span><span>影像 PET {state.pet_count} 层 / CT {state.ct_count} 层</span><span>定量 {state.exam.attenuation_corrected ? state.correction_label : '需复核'}</span><span className="status-spacer" /><span>当前视口 {LABELS[activeView]}</span><span>缩放 {Math.round(zoom * 100)}%</span><span>{tool === 'align' ? `单点对齐：${alignMarks.basePet ? '基线已选' : '点击基线 PET'} · ${alignMarks.currentPet ? '本次已选' : '点击本次 PET'}` : tool === 'blood_pool' ? '在本次 PET 点击血池中心' : tool === 'liver' ? '在本次 PET 点击肝右叶中心' : activeAlignment ? '单点平移对齐 · 请核对解剖' : '比例翻层不代表空间配准'}</span></footer>
  </div>
}

export default App
