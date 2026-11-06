import React, { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { ShopOffer, UserLocation } from '../types';
import { MAP_TILE_URL } from '../api/client';
import { MapPin, Navigation } from 'lucide-react';

interface InteractiveMapProps {
  offers: ShopOffer[];
  userLocation: UserLocation;
  selectedOfferId?: string | null;
  onSelectOffer?: (offer: ShopOffer) => void;
  onStartShoppingTrip?: (offer: ShopOffer) => void;
}

export const InteractiveMap: React.FC<InteractiveMapProps> = ({
  offers,
  userLocation,
  selectedOfferId,
  onSelectOffer,
  onStartShoppingTrip,
}) => {
  const mapContainerRef = useRef<HTMLDivElement | null>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const markersLayerRef = useRef<L.LayerGroup | null>(null);

  useEffect(() => {
    if (!mapContainerRef.current || mapInstanceRef.current) return;

    const map = L.map(mapContainerRef.current, {
      center: [userLocation.lat, userLocation.lng],
      zoom: 12,
      zoomControl: true,
      attributionControl: false,
    });

    L.tileLayer(MAP_TILE_URL, {
      maxZoom: 19,
      subdomains: 'abcd',
    }).addTo(map);

    markersLayerRef.current = L.layerGroup().addTo(map);
    mapInstanceRef.current = map;

    return () => {
      map.remove();
      mapInstanceRef.current = null;
      markersLayerRef.current = null;
    };
  }, [userLocation.lat, userLocation.lng]);

  useEffect(() => {
    const map = mapInstanceRef.current;
    const layer = markersLayerRef.current;
    if (!map || !layer) return;

    layer.clearLayers();
    const boundsPoints: L.LatLngExpression[] = [[userLocation.lat, userLocation.lng]];

    // 1. User Location Pin
    const userIcon = L.divIcon({
      className: 'torob-user-pin',
      html: `
        <div style="display:flex;align-items:center;gap:4px;background:#0ea5e9;color:#fff;padding:3px 8px;border-radius:999px;font-family:'Vazirmatn',sans-serif;font-size:10px;font-weight:800;border:2px solid #fff;box-shadow:0 0 14px rgba(14,165,233,0.7);white-space:nowrap;direction:rtl;">
          <span>📍 موقعیت شما (${userLocation.name})</span>
        </div>
      `,
      iconSize: [120, 26],
      iconAnchor: [60, 13],
    });
    L.marker([userLocation.lat, userLocation.lng], { icon: userIcon }).addTo(layer);

    // 2. Store Price & Mall Pins
    offers.slice(0, 15).forEach((offer, idx) => {
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
        ? '#ff8fa9'
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
          <div style="display:inline-flex;align-items:center;gap:5px;background:${bg};color:#fff;padding:4px 9px;border-radius:12px;font-family:'Vazirmatn',sans-serif;font-size:11px;font-weight:800;border:2px solid ${border};box-shadow:0 4px 14px rgba(0,0,0,0.65);white-space:nowrap;direction:rtl;transform:${isSelected ? 'scale(1.08)' : 'scale(1)'};">
            <span style="width:7px;height:7px;border-radius:999px;background:${offer.isOpenNow ? '#10b981' : '#f59e0b'};display:inline-block;"></span>
            <span>${priceLabel}</span>
          </div>
        `,
        iconSize: [86, 28],
        iconAnchor: [43, 14],
      });

      const mallBadgeHtml = [offer.mallName, offer.mallFloor, offer.mallUnit]
        .filter(Boolean)
        .join(' • ');

      const marker = L.marker([lat, lng], { icon: storeIcon }).addTo(layer);
      marker.bindPopup(
        `<div style="direction:rtl;text-align:right;font-family:'Vazirmatn',sans-serif;min-width:190px;color:#111;">
          <div style="font-weight:900;font-size:12px;margin-bottom:3px;color:#e9325a;">${offer.shopName}</div>
          ${mallBadgeHtml ? `<div style="font-size:10px;font-weight:700;color:#374151;margin-bottom:4px;">🏢 ${mallBadgeHtml}</div>` : ''}
          <div style="font-size:11px;font-weight:800;margin-bottom:3px;">💰 ${offer.price.toLocaleString('fa-IR')} تومان</div>
          <div style="font-size:10px;color:#4b5563;">🚗 فاصله: ${offer.distanceKm.toLocaleString('fa-IR')} کیلومتر (${offer.estimatedDrivingMins.toLocaleString('fa-IR')} دقیقه)</div>
        </div>`
      );

      marker.on('click', () => {
        onSelectOffer?.(offer);
      });
    });

    if (boundsPoints.length > 1) {
      map.fitBounds(L.latLngBounds(boundsPoints), { padding: [32, 32], maxZoom: 14 });
    } else {
      map.setView([userLocation.lat, userLocation.lng], 13);
    }
  }, [offers, userLocation, selectedOfferId, onSelectOffer, onStartShoppingTrip]);

  return (
    <div className="rounded-2xl overflow-hidden border border-[#252536] bg-[#12121a] shadow-lg">
      <div className="px-3.5 py-2.5 bg-[#151520] border-b border-[#232332] flex items-center justify-between flex-wrap gap-2 text-xs">
        <div className="flex items-center gap-2 font-extrabold text-white">
          <MapPin className="w-4 h-4 text-[#e9325a]" />
          <span>نقشه زنده فروشگاه‌های حضوری تهران (پین قیمت و پاساژ)</span>
        </div>
        <div className="flex items-center gap-3 text-[11px] text-neutral-300">
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-emerald-400" />
            <span>باز در این لحظه</span>
          </span>
          <span className="inline-flex items-center gap-1">
            <span className="w-2 h-2 rounded-full bg-[#e9325a]" />
            <span>منتخب الگوریتم</span>
          </span>
          <span className="inline-flex items-center gap-1 text-sky-400 font-bold">
            <Navigation className="w-3 h-3" />
            <span>مبدا: {userLocation.name}</span>
          </span>
        </div>
      </div>
      <div
        ref={mapContainerRef}
        className="w-full h-60 sm:h-72 bg-[#0d0d14]"
        aria-label="نقشه فروشگاه‌های حضوری تهران"
      />
    </div>
  );
};
