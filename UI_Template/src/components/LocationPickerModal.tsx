import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { MapPin, Check, X, Moon, Sun } from 'lucide-react';
import { UserLocation } from '../types';

const OSM_PERSIAN_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const MAP_STYLE_STORAGE_KEY = 'torob_map_style';

// Offline Tehran reference centroids solely to generate a readable Persian label for any clicked coordinate
const TEHRAN_AREA_CENTROIDS: Array<{ name: string; area: string; lat: number; lng: number }> = [
  { name: 'میدان ولیعصر', area: 'مرکز تهران', lat: 35.7118, lng: 51.4072 },
  { name: 'خیابان جمهوری', area: 'مرکز تهران', lat: 35.6944, lng: 51.4116 },
  { name: 'میدان انقلاب', area: 'مرکز تهران', lat: 35.7013, lng: 51.3911 },
  { name: 'یوسف‌آباد / امیرآباد', area: 'مرکز تهران', lat: 35.7295, lng: 51.4015 },
  { name: 'عباس‌آباد / بهشتی', area: 'مرکز تهران', lat: 35.7282, lng: 51.4288 },
  { name: 'میدان ونک', area: 'شمال تهران', lat: 35.7575, lng: 51.4101 },
  { name: 'میرداماد / شریعتی', area: 'شمال تهران', lat: 35.7602, lng: 51.4335 },
  { name: 'جردن (نلسون ماندلا)', area: 'شمال تهران', lat: 35.7745, lng: 51.4158 },
  { name: 'تجریش / شمیران', area: 'شمال تهران', lat: 35.8053, lng: 51.4312 },
  { name: 'نیاوران / فرمانیه', area: 'شمال شرق تهران', lat: 35.8112, lng: 51.4695 },
  { name: 'پاسداران / هروی', area: 'شمال شرق تهران', lat: 35.7712, lng: 51.4662 },
  { name: 'سعادت‌آباد', area: 'شمال غرب تهران', lat: 35.7836, lng: 51.3721 },
  { name: 'شهرک غرب', area: 'شمال غرب تهران', lat: 35.7592, lng: 51.3695 },
  { name: 'پونک / بزرگراه ستاری', area: 'غرب تهران', lat: 35.7598, lng: 51.3318 },
  { name: 'صادقیه (آریاشهر)', area: 'غرب تهران', lat: 35.7219, lng: 51.3347 },
  { name: 'شهرک اکباتان', area: 'غرب تهران', lat: 35.7088, lng: 51.3115 },
  { name: 'میدان آزادی', area: 'غرب تهران', lat: 35.6997, lng: 51.3381 },
  { name: 'چیتگر / دریاچه', area: 'غرب تهران', lat: 35.7415, lng: 51.2155 },
  { name: 'رسالت / نارمک', area: 'شرق تهران', lat: 35.7368, lng: 51.4945 },
  { name: 'تهرانپارس', area: 'شرق تهران', lat: 35.7362, lng: 51.5362 },
  { name: 'پیروزی / نیروهوایی', area: 'شرق تهران', lat: 35.6912, lng: 51.4795 },
  { name: 'بازار بزرگ تهران', area: 'جنوب و مرکز تهران', lat: 35.6749, lng: 51.4215 },
  { name: 'نازی‌آباد / راه‌آهن', area: 'جنوب تهران', lat: 35.6435, lng: 51.4012 },
  { name: 'شهرری', area: 'جنوب تهران', lat: 35.5935, lng: 51.4342 },
];

function haversineKm(lat1: number, lng1: number, lat2: number, lng2: number): number {
  const toRad = (deg: number) => (deg * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLng = toRad(lng2 - lng1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLng / 2) ** 2;
  return 6371 * 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
}

export function resolveTehranLocationLabel(lat: number, lng: number): {
  name: string;
  area: string;
} {
  let best = TEHRAN_AREA_CENTROIDS[0];
  let minKm = Infinity;
  for (const item of TEHRAN_AREA_CENTROIDS) {
    const d = haversineKm(lat, lng, item.lat, item.lng);
    if (d < minKm) {
      minKm = d;
      best = item;
    }
  }
  if (minKm <= 1.2) {
    return { name: best.name, area: best.area };
  }
  if (minKm <= 4.5) {
    return { name: `محدوده ${best.name}`, area: best.area };
  }
  const latFa = lat.toLocaleString('fa-IR', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  const lngFa = lng.toLocaleString('fa-IR', { minimumFractionDigits: 3, maximumFractionDigits: 3 });
  return { name: `موقعیت انتخابی (${latFa}، ${lngFa})`, area: 'تهران' };
}

function clampTehranCoords(lat: number, lng: number): { lat: number; lng: number } {
  return {
    lat: Number(Math.max(35.48, Math.min(35.92, lat)).toFixed(5)),
    lng: Number(Math.max(51.02, Math.min(51.72, lng)).toFixed(5)),
  };
}

function readMapStyle(): 'persian_osm' | 'dark' {
  if (typeof window === 'undefined') return 'persian_osm';
  try {
    return window.localStorage.getItem(MAP_STYLE_STORAGE_KEY) === 'dark'
      ? 'dark'
      : 'persian_osm';
  } catch {
    return 'persian_osm';
  }
}

interface LocationPickerModalProps {
  isOpen: boolean;
  initialLocation: UserLocation;
  onClose: () => void;
  onConfirmLocation: (location: UserLocation) => void;
}

export const LocationPickerModal: React.FC<LocationPickerModalProps> = ({
  isOpen,
  initialLocation,
  onClose,
  onConfirmLocation,
}) => {
  const [draftCoords, setDraftCoords] = useState<{ lat: number; lng: number }>({
    lat: initialLocation.lat,
    lng: initialLocation.lng,
  });
  const [mapStyle, setMapStyle] = useState<'persian_osm' | 'dark'>(readMapStyle);

  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<L.Map | null>(null);
  const markerRef = useRef<L.Marker | null>(null);

  const resolvedLabel = resolveTehranLocationLabel(draftCoords.lat, draftCoords.lng);

  const buildPinIcon = (label: string) =>
    L.divIcon({
      className: 'torob-picker-pin',
      html: `
        <div style="display:flex;flex-direction:column;align-items:center;transform:translateY(-14px);">
          <div style="background:#e9325a;color:#fff;padding:4px 10px;border-radius:999px;font-family:'Vazirmatn',sans-serif;font-size:11px;font-weight:900;border:2px solid #fff;box-shadow:0 6px 18px rgba(233,50,90,0.65);white-space:nowrap;direction:rtl;">
            📍 ${label}
          </div>
          <div style="width:3px;height:10px;background:#fff;border-radius:2px;box-shadow:0 2px 6px rgba(0,0,0,0.6);"></div>
        </div>
      `,
      iconSize: [160, 40],
      iconAnchor: [80, 26],
    });

  useEffect(() => {
    if (!isOpen) return;
    setDraftCoords({ lat: initialLocation.lat, lng: initialLocation.lng });
  }, [isOpen, initialLocation.lat, initialLocation.lng]);

  useEffect(() => {
    if (!isOpen) return;
    const container = mapContainerRef.current;
    if (!container || mapRef.current) return;

    const startLat = initialLocation.lat;
    const startLng = initialLocation.lng;

    const map = L.map(container, {
      center: [startLat, startLng],
      zoom: 13,
      zoomControl: true,
      attributionControl: false,
    });

    L.tileLayer(OSM_PERSIAN_TILE_URL, { maxZoom: 19 }).addTo(map);
    container.classList.toggle('torob-map-night', mapStyle === 'dark');

    const startResolved = resolveTehranLocationLabel(startLat, startLng);
    const marker = L.marker([startLat, startLng], {
      draggable: true,
      icon: buildPinIcon(startResolved.name),
      zIndexOffset: 1000,
    }).addTo(map);

    map.on('click', (e: L.LeafletMouseEvent) => {
      const clamped = clampTehranCoords(e.latlng.lat, e.latlng.lng);
      marker.setLatLng([clamped.lat, clamped.lng]);
      const lbl = resolveTehranLocationLabel(clamped.lat, clamped.lng);
      marker.setIcon(buildPinIcon(lbl.name));
      setDraftCoords(clamped);
    });

    marker.on('dragend', () => {
      const pos = marker.getLatLng();
      const clamped = clampTehranCoords(pos.lat, pos.lng);
      marker.setLatLng([clamped.lat, clamped.lng]);
      const lbl = resolveTehranLocationLabel(clamped.lat, clamped.lng);
      marker.setIcon(buildPinIcon(lbl.name));
      setDraftCoords(clamped);
    });

    mapRef.current = map;
    markerRef.current = marker;

    const timers = [
      window.setTimeout(() => map.invalidateSize(), 60),
      window.setTimeout(() => map.invalidateSize(), 220),
    ];

    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      map.remove();
      mapRef.current = null;
      markerRef.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen]);

  useEffect(() => {
    const container = mapContainerRef.current;
    if (container) {
      container.classList.toggle('torob-map-night', mapStyle === 'dark');
    }
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(MAP_STYLE_STORAGE_KEY, mapStyle);
      } catch {
        // ignore
      }
    }
  }, [mapStyle]);

  if (!isOpen) return null;

  const handleConfirm = () => {
    onConfirmLocation({
      id: `custom_${draftCoords.lat}_${draftCoords.lng}`,
      name: resolvedLabel.name,
      area: resolvedLabel.area,
      lat: draftCoords.lat,
      lng: draftCoords.lng,
    });
    onClose();
  };

  return (
    <div
      dir="rtl"
      className="fixed inset-0 z-50 flex items-center justify-center p-3 sm:p-5 bg-black/80 backdrop-blur-sm animate-fade-in font-sans"
      onClick={onClose}
    >
      <div
        className="w-full max-w-2xl rounded-2xl bg-[#111118] border border-[#2a2a3c] shadow-2xl overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="px-4 py-3.5 bg-[#151520] border-b border-[#232334] flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-xl bg-[#e9325a]/15 border border-[#e9325a]/30 flex items-center justify-center text-[#ff4d79]">
              <MapPin className="w-4 h-4" />
            </div>
            <div>
              <h3 className="text-sm font-black text-white">
                انتخاب دستی موقعیت مکانی شما روی نقشه تهران
              </h3>
              <p className="text-[11px] text-neutral-400">
                روی هر نقطه از نقشه کلیک کنید یا پین را بکشید تا مسافت و رتبهٔ مغازه‌ها از همان نقطه محاسبه شود
              </p>
            </div>
          </div>

          <div className="flex items-center gap-1.5 shrink-0">
            <button
              type="button"
              onClick={() =>
                setMapStyle((prev) => (prev === 'persian_osm' ? 'dark' : 'persian_osm'))
              }
              className="px-2.5 py-1.5 rounded-xl bg-[#1d1d2b] hover:bg-[#27273a] border border-[#323248] text-[11px] font-bold text-white flex items-center gap-1.5 cursor-pointer transition-colors"
              title="تغییر ظاهر نقشه"
            >
              {mapStyle === 'persian_osm' ? (
                <>
                  <Moon className="w-3.5 h-3.5 text-[#ff80a0]" />
                  <span>حالت شب</span>
                </>
              ) : (
                <>
                  <Sun className="w-3.5 h-3.5 text-amber-400" />
                  <span>حالت روز</span>
                </>
              )}
            </button>

            <button
              type="button"
              onClick={onClose}
              className="p-2 rounded-xl text-neutral-400 hover:text-white hover:bg-white/10 transition-colors cursor-pointer"
              title="بستن"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
        </div>

        {/* Interactive Leaflet Map */}
        <div className={mapStyle === 'dark' ? 'torob-map-night' : ''}>
          <div
            ref={mapContainerRef}
            className="w-full h-72 sm:h-96 bg-[#181822] cursor-crosshair"
            style={{ minHeight: '300px' }}
          />
        </div>

        {/* Selected Coordinate Summary + Confirm Button */}
        <div className="p-4 bg-[#14141d] border-t border-[#232334] flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 shrink-0 animate-pulse" />
            <div className="min-w-0">
              <div className="text-xs font-extrabold text-white truncate">
                مبدأ انتخابی: {resolvedLabel.name}{' '}
                <span className="text-neutral-400 font-medium">({resolvedLabel.area})</span>
              </div>
              <div className="text-[11px] text-neutral-400 font-mono">
                عرض جغرافیایی:{' '}
                {draftCoords.lat.toLocaleString('fa-IR', {
                  minimumFractionDigits: 4,
                  maximumFractionDigits: 4,
                })}{' '}
                · طول جغرافیایی:{' '}
                {draftCoords.lng.toLocaleString('fa-IR', {
                  minimumFractionDigits: 4,
                  maximumFractionDigits: 4,
                })}
              </div>
            </div>
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={onClose}
              className="px-3.5 py-2 rounded-xl bg-[#1e1e2b] hover:bg-[#282838] text-neutral-300 text-xs font-bold border border-[#2f2f42] transition-colors cursor-pointer"
            >
              انصراف
            </button>
            <button
              type="button"
              onClick={handleConfirm}
              className="px-4 py-2 rounded-xl bg-gradient-to-r from-[#e9325a] to-[#ff4d79] hover:opacity-95 text-white text-xs font-extrabold flex items-center gap-1.5 shadow-lg shadow-[#e9325a]/30 transition-all cursor-pointer"
            >
              <Check className="w-4 h-4" />
              <span>ثبت موقعیت و محاسبه پیشنهادها</span>
            </button>
          </div>
        </div>
      </div>
    </div>
  );
};
