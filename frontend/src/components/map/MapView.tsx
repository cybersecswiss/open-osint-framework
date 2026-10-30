import { useEffect, useMemo, useRef } from 'react'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { Empty, Card, Timeline, Typography, Rate } from 'antd'
import { useTranslation } from 'react-i18next'
import { NODE_COLORS } from '../graph/GraphView'

const { Text } = Typography

/**
 * Geographic footprint of a case: an OpenStreetMap map of every entity with
 * coordinates (e.g. Google-Maps review places, Telegram geo), plus a review
 * timeline beside it (sorted newest-first). Clicking a place — on the map or
 * in the timeline — shows what was reviewed (rating, comment, date).
 */

interface LocatedPoint {
  id: string
  label: string
  type: string
  lat: number
  lon: number
  address: string
  rating: number | null
  comment: string
  date: string
}

const inRange = (lat: number, lon: number) =>
  Number.isFinite(lat) && Number.isFinite(lon) &&
  Math.abs(lat) <= 90 && Math.abs(lon) <= 180 && !(lat === 0 && lon === 0)

export function extractCoords(entity: any): { lat: number; lon: number } | null {
  const d = (entity && entity.data) || {}
  const num = (v: any) => (typeof v === 'string' ? parseFloat(v) : v)
  const pairs: [any, any][] = [
    [d.lat, d.lon], [d.latitude, d.longitude], [d.lat, d.lng], [d.lat, d.long],
  ]
  for (const [a, b] of pairs) {
    const lat = num(a), lon = num(b)
    if (inRange(lat, lon)) return { lat, lon }
  }
  for (const s of [d.coords, d.geo, d.latlng, d.position]) {
    if (typeof s === 'string' && s.includes(',')) {
      const [a, b] = s.split(',').map((x) => parseFloat(x.trim()))
      if (inRange(a, b)) return { lat: a, lon: b }
    }
  }
  return null
}

export function countLocated(entities: any[]): number {
  return (entities || []).reduce((n, e) => (extractCoords(e) ? n + 1 : n), 0)
}

const esc = (s: string) =>
  String(s).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' } as any)[c])

const stars = (r: number | null) =>
  r ? '★'.repeat(r) + '☆'.repeat(Math.max(0, 5 - r)) : ''

export default function MapView({ entities }: { entities: any[] }) {
  const { t } = useTranslation()
  const divRef = useRef<HTMLDivElement>(null)
  const mapRef = useRef<L.Map | null>(null)
  const layerRef = useRef<L.FeatureGroup | null>(null)
  const markersRef = useRef<Record<string, L.Marker>>({})

  const points = useMemo<LocatedPoint[]>(() => {
    const out: LocatedPoint[] = []
    for (const e of entities || []) {
      const c = extractCoords(e)
      if (!c) continue
      const d = e.data || {}
      out.push({
        id: String(e.id), label: e.label || e.id, type: e.entity_type,
        lat: c.lat, lon: c.lon,
        address: String(d.address || d.place || ''),
        rating: typeof d.rating === 'number' ? d.rating : null,
        comment: String(d.comment || ''),
        date: String(d.review_date || d.date || ''),
      })
    }
    return out
  }, [entities])

  // Reviews for the timeline: located points that carry a date/rating/comment,
  // newest first; undated ones go last.
  const timeline = useMemo(() => (
    points
      .filter((p) => p.date || p.comment || p.rating != null)
      .sort((a, b) => (b.date || '').localeCompare(a.date || ''))
  ), [points])

  const focus = (p: LocatedPoint) => {
    const m = markersRef.current[p.id]
    if (m && mapRef.current) {
      mapRef.current.flyTo([p.lat, p.lon], 14, { duration: 0.6 })
      m.openPopup()
    }
  }

  useEffect(() => {
    if (!divRef.current || points.length === 0) return
    if (!mapRef.current) {
      mapRef.current = L.map(divRef.current, { scrollWheelZoom: true })
      L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
      }).addTo(mapRef.current)
    }
    const map = mapRef.current
    if (layerRef.current) { layerRef.current.remove(); layerRef.current = null }
    markersRef.current = {}
    const group = L.featureGroup()
    for (const p of points) {
      const color = (NODE_COLORS as any)[p.type] || NODE_COLORS.default
      const icon = L.divIcon({
        className: '', iconSize: [16, 16], iconAnchor: [8, 8],
        html: `<div style="width:14px;height:14px;border-radius:50%;background:${color};` +
              `border:2px solid #fff;box-shadow:0 0 3px rgba(0,0,0,.5)"></div>`,
      })
      const popup =
        `<b>${esc(p.label)}</b>` +
        (p.address ? `<br><span style="color:#888">${esc(p.address)}</span>` : '') +
        (p.rating ? `<br><span style="color:#fa8c16">${stars(p.rating)}</span>` : '') +
        (p.date ? ` <span style="color:#888">${esc(p.date.slice(0, 10))}</span>` : '') +
        (p.comment ? `<br>${esc(p.comment)}` : '') +
        `<br><span style="color:#aaa;font-size:11px">${p.lat.toFixed(5)}, ${p.lon.toFixed(5)}</span>`
      const m = L.marker([p.lat, p.lon], { icon, title: p.label })
        .bindPopup(popup, { maxWidth: 320 })
      m.addTo(group)
      markersRef.current[p.id] = m
    }
    group.addTo(map)
    layerRef.current = group
    if (points.length === 1) map.setView([points[0].lat, points[0].lon], 12)
    else map.fitBounds(group.getBounds().pad(0.2))
    setTimeout(() => map.invalidateSize(), 0)
  }, [points])

  useEffect(() => () => { mapRef.current?.remove(); mapRef.current = null }, [])

  if (points.length === 0) {
    return <Empty description={t('case_detail.map_empty')} style={{ padding: '60px 0' }} />
  }

  return (
    <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', alignItems: 'stretch' }}>
      <div ref={divRef}
        style={{ flex: '1 1 420px', minWidth: 0, height: '72vh', borderRadius: 8, overflow: 'hidden' }} />
      {timeline.length > 0 && (
        <Card size="small"
          title={t('case_detail.map_timeline', { count: timeline.length })}
          styles={{ body: { padding: 12, overflowY: 'auto', height: 'calc(72vh - 40px)' } }}
          style={{ width: 360, flex: '0 0 360px', height: '72vh' }}>
          <Timeline
            items={timeline.map((p) => ({
              color: (NODE_COLORS as any)[p.type] || '#fa8c16',
              children: (
                <div style={{ cursor: 'pointer' }} onClick={() => focus(p)}>
                  {p.date && <Text type="secondary" style={{ fontSize: 12 }}>{p.date.slice(0, 10)}</Text>}
                  <div><Text strong>{p.label}</Text></div>
                  {p.rating != null && (
                    <Rate disabled value={p.rating} style={{ fontSize: 12 }} />
                  )}
                  {p.comment && (
                    <div><Text type="secondary" style={{ fontSize: 12 }}>{p.comment.slice(0, 160)}</Text></div>
                  )}
                </div>
              ),
            }))}
          />
        </Card>
      )}
    </div>
  )
}
