import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { ShopOffer, UserLocation } from '../types';
import { MapPin, Navigation, Moon, Sun } from 'lucide-react';

const OSM_PERSIAN_TILE_URL = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const MAP_STYLE_STORAGE_KEY = 'torob_map_style';

function readInitialMapStyle(): 'persian_osm' | 'dark' {
  if (typeof window === 'undefined') return 'persian_osm';
  try {
    return window.localStorage.getItem(MAP_STYLE_STORAGE_KEY) === 'dark'
      ? 'dark'
      : 'persian_osm';
  } catch {
    return 'persian_osm';
  }
}

interface InteractiveMapProps {
  offers: ShopOffer[];
  userLocation: UserLocation;
  selectedOfferId?: string | null;
  onSelectOffer?: (offer: ShopOffer) => void;
  onStartShoppingTrip?: (offer: ShopOffer) => void;
  onChangeLocation?: () => void;
  compact?: boolean;
}

export const InteractiveMap: React.FC<InteractiveMapProps> = ({
  offers,
  userLocation,
  selectedOfferId,
  onSelectOffer,
  onStartShoppingTrip,
  onChangeLocation,
  compact = false,
}) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);
  const [mapStyle, setMapStyle] = useState<'persian_osm' | 'dark'>(readInitialMapStyle);

  // Initialize Leaflet map and ResizeObserver so tiles never render blank inside modals/tabs
  useEffect(() => {
    const container = mapContainerRef.current;
    if (!container || mapInstanceRef.current) return;

    const map = L.map(container, {
      center: [userLocation.lat, userLocation.lng],
      zoom: 12,
      zoomControl: true,
      attributionControl: false,
    });

    L.tileLayer(OSM_PERSIAN_TILE_URL, {
      maxZoom: 19,
    }).addTo(map);

    markersLayerRef.current = L.layerGroup().addTo(map);
    mapInstanceRef.current = map;

    const timers = [
      window.setTimeout(() => map.invalidateSize(), 60),
      window.setTimeout(() => map.invalidateSize(), 220),
      window.setTimeout(() => map.invalidateSize(), 500),
    ];

    let resizeObserver: ResizeObserver | null = null;
    if (typeof ResizeObserver !== 'undefined') {
      resizeObserver = new ResizeObserver(() => {
        map.invalidateSize();
      });
      resizeObserver.observe(container);
    }

    return () => {
      timers.forEach((t) => window.clearTimeout(t));
      resizeObserver?.disconnect();
      map.remove();
      mapInstanceRef.current = null;
      markersLayerRef.current = null;
    };
  }, [userLocation.lat, userLocation.lng]);

  // Toggle night-mode class imperatively on Leaflet container (without React clobbering `leaflet-container` classes) and persist preference
  useEffect(() => {
    const container = mapContainerRef.current;
    if (container) {
      container.classList.toggle('torob-map-night', mapStyle === 'dark');
    }
    if (typeof window !== 'undefined') {
      try {
        window.localStorage.setItem(MAP_STYLE_STORAGE_KEY, mapStyle);
      } catch {
        // ignore storage errors
      }
    }
  }, [mapStyle]);

  // Render user pin, store pins, and live route polyline
  useEffect(() => {
    const map = mapInstanceRef.current;
    const layer = markersLayerRef.current;
    if (!map || !layer) return;

    map.invalidateSize();
    layer.clearLayers();
    const boundsPoints: L.LatLngExpression[] = [[userLocation.lat, userLocation.lng]];

    // 1. User Location Pin
    const userIcon = L.divIcon({
      className: 'torob-user-pin',
      html: `
        <div style="display:flex;align-items:center;gap:4px;background:#0284c7;color:#fff;padding:4px 10px;border-radius:999px;font-family:'Vazirmatn',sans-serif;font-size:11px;font-weight:900;border:2px solid #fff;box-shadow:0 4px 14px rgba(2,132,199,0.75);white-space:nowrap;direction:rtl;">
          <span>📍 مبدا شما (${userLocation.name})</span>
        </div>
      `,
      iconSize: [140, 28],
      iconAnchor: [70, 14],
    });
    L.marker([userLocation.lat, userLocation.lng], { icon: userIcon, zIndexOffset: 500 }).addTo(layer);

    const visibleOffers = offers.slice(0, 15);
    const activeOffer =
      visibleOffers.find((o) => o.id === selectedOfferId) || visibleOffers[0] || null;

    // 2. Draw direct visual route line from user location to active/selected store
    if (activeOffer) {
      const destLat = activeOffer.coordinates?.lat || 35.7219;
      const destLng = activeOffer.coordinates?.lng || 51.3347;
      L.polyline(
        [
          [userLocation.lat, userLocation.lng],
          [destLat, destLng],
        ],
        {
          color: '#e9325a',
          weight: 4,
          opacity: 0.9,
          dashArray: '8, 8',
        }
      ).addTo(layer);
    }

    // 3. Store Price & Mall Pins
    visibleOffers.forEach((offer, idx) => {
      const lat = offer.coordinates?.lat || 35.7219;
      const lng = offer.coordinates?.lng || 51.3347;
      boundsPoints.push([lat, lng]);

      const isSelected = selectedOfferId ? offer.id === selectedOfferId : idx === 0;
      const bg = isSelected
        ? '#e9325a'
        : offer.isOpenNow
          ? '#161622'
          : '#261820';
      const border = isSelected
        ? '#ffffff'
        : offer.isOpenNow
          ? '#10b981'
          : '#6b7280';

      const priceLabel =
        offer.price > 0
          ? `${(offer.price / 1_000_000).toLocaleString('fa-IR', { maximumFractionDigits: 1 })} م`
          : 'استعلام';

      const storeIcon = L.divIcon({
        className: 'torob-store-pin',
        html: `
          <div style="display:inline-flex;align-items:center;gap:5px;background:${bg};color:#fff;padding:4px 10px;border-radius:12px;font-family:'Vazirmatn',sans-serif;font-size:11px;font-weight:900;border:2px solid ${border};box-shadow:0 4px 14px rgba(0,0,0,0.7);white-space:nowrap;direction:rtl;transform:${isSelected ? 'scale(1.12)' : 'scale(1)'};">
            <span style="width:7px;height:7px;border-radius:999px;background:${offer.isOpenNow ? '#10b981' : '#f59e0b'};display:inline-block;"></span>
            <span>${compact ? offer.shopName : priceLabel}</span>
          </div>
        `,
        iconSize: [compact ? 130 : 92, 30],
        iconAnchor: [compact ? 65 : 46, 15],
      });

      const mallBadgeHtml = [offer.mallName, offer.mallFloor, offer.mallUnit]
        .filter(Boolean)
        .join(' • ');

      const marker = L.marker([lat, lng], {
        icon: storeIcon,
        zIndexOffset: isSelected ? 1000 : 100,
      }).addTo(layer);

      marker.bindPopup(
        `<div style="direction:rtl;text-align:right;font-family:'Vazirmatn',sans-serif;min-width:200px;color:#111;">
          <div style="font-weight:900;font-size:12px;margin-bottom:3px;color:#e9325a;">🏪 ${offer.shopName}</div>
          ${mallBadgeHtml ? `<div style="font-size:10px;font-weight:700;color:#374151;margin-bottom:4px;">🏢 ${mallBadgeHtml}</div>` : ''}
          <div style="font-size:11px;font-weight:800;margin-bottom:3px;">💰 ${offer.price.toLocaleString('fa-IR')} تومان</div>
          <div style="font-size:10px;color:#4b5563;">🚗 فاصله: ${offer.distanceKm.toLocaleString('fa-IR')} کیلومتر (~${(offer.estimatedDrivingMins || 10).toLocaleString('fa-IR')} دقیقه)</div>
        </div>`
      );

      marker.on('click', () => {
        onSelectOffer?.(offer);
      });
    });

    if (boundsPoints.length > 1) {
      map.fitBounds(L.latLngBounds(boundsPoints), { padding: [36, 36], maxZoom: 14 });
    } else {
      map.setView([userLocation.lat, userLocation.lng], 13);
    }
  }, [offers, userLocation, selectedOfferId, onSelectOffer, onStartShoppingTrip, compact]);

  return (
    <div className="rounded-2xl overflow-hidden border border-[#2c2c3e] bg-[#12121a] shadow-lg">
      <div className="px-3.5 py-2.5 bg-[#151520] border-b border-[#232332] flex items-center justify-between flex-wrap gap-2 text-xs">
        <div className="flex items-center gap-2 font-extrabold text-white">
          <MapPin className="w-4 h-4 text-[#e9325a]" />
          <span>
            {compact
              ? 'پیش‌نمایش مسیر و موقعیت فروشگاه روی نقشه تهران'
              : 'نقشه زنده فروشگاه‌های حضوری تهران (پین قیمت و مسیر)'}
          </span>
        </div>
        <div className="flex items-center gap-2.5 text-[11px] text-neutral-300">
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span>باز</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#e9325a]" />
            <span>مقصد منتخب</span>
          </span>
          {onChangeLocation ? (
            <button
              type="button"
              onClick={onChangeLocation}
              className="inline-flex items-center gap-1 px-2 py-0.5 rounded-lg bg-sky-500/10 hover:bg-sky-500/20 border border-sky-500/30 text-sky-300 font-bold cursor-pointer transition-colors"
              title="تغییر دستی موقعیت مبدأ روی نقشه"
            >
              <Navigation className="w-3 h-3" />
              <span>مبدا: {userLocation.name} (تغییر)</span>
            </button>
          ) : (
            <span className="inline-flex items-center gap-1 text-sky-400 font-bold">
              <Navigation className="w-3 h-3" />
              <span>مبدا: {userLocation.name}</span>
            </span>
          )}
          <button
            type="button"
            onClick={() =>
              setMapStyle((prev) => (prev === 'persian_osm' ? 'dark' : 'persian_osm'))
            }
            className="px-2.5 py-1 rounded-lg bg-[#20202e] hover:bg-[#2b2b3e] border border-[#34344a] text-[10px] font-bold text-white flex items-center gap-1.5 cursor-pointer transition-colors"
            title="تغییر ظاهر نقشه (حالت روز / شب)"
          >
            {mapStyle === 'persian_osm' ? (
              <>
                <Moon className="w-3 h-3 text-[#ff80a0]" />
                <span>حالت شب</span>
              </>
            ) : (
              <>
                <Sun className="w-3 h-3 text-amber-400" />
                <span>حالت روز</span>
              </>
            )}
          </button>
        </div>
      </div>
      <div className={mapStyle === 'dark' ? 'torob-map-night' : ''}>
        <div
          ref={mapContainerRef}
          className={`w-full ${compact ? 'h-52 sm:h-60' : 'h-64 sm:h-80'} bg-[#181822]`}
          style={{ minHeight: compact ? '210px' : '260px' }}
          aria-label="نقشه فروشگاه‌های حضوری تهران"
        />
      </div>
    </div>
  );
};
