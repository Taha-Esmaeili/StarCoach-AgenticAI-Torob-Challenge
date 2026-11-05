import { ShopOffer, RankingWeights, RankedOffer, NormalizedScores, UserLocation } from '../types';

/**
 * Calculates geographic distance in kilometers using the Haversine formula
 */
export function calculateHaversineDistance(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number
): number {
  const R = 6371; // Earth's radius in km
  const dLat = ((lat2 - lat1) * Math.PI) / 180;
  const dLon = ((lon2 - lon1) * Math.PI) / 180;
  const a =
    Math.sin(dLat / 2) * Math.sin(dLat / 2) +
    Math.cos((lat1 * Math.PI) / 180) *
      Math.cos((lat2 * Math.PI) / 180) *
      Math.sin(dLon / 2) *
      Math.sin(dLon / 2);
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return Math.round(R * c * 10) / 10;
}

/**
 * Normalizes an array of numbers using percentile rank or min-max normalization
 * Higher value => higher score (0 to 1)
 */
function normalizeValues(values: number[], invert: boolean = false): number[] {
  if (values.length === 0) return [];
  if (values.length === 1) return [1.0];

  const min = Math.min(...values);
  const max = Math.max(...values);

  if (max === min) {
    return values.map(() => 0.5);
  }

  return values.map((v) => {
    let norm = (v - min) / (max - min);
    if (invert) {
      norm = 1.0 - norm; // Lower is better (e.g. price, distance)
    }
    return Math.max(0, Math.min(1, Math.round(norm * 100) / 100));
  });
}

/**
 * Validates and normalizes weights so that sum(w_i) = 1.0 and minimum relevance is guaranteed
 */
export function sanitizeWeights(raw: RankingWeights): RankingWeights {
  const minRelevance = 0.15;
  const clampedRelevance = Math.max(minRelevance, Math.min(0.7, raw.relevance));

  const keys: (keyof RankingWeights)[] = [
    'relevance',
    'distance',
    'price',
    'reputation',
    'stockFreshness',
    'creditSupport',
  ];

  let sumNonRelevance = 0;
  for (const k of keys) {
    if (k !== 'relevance') {
      sumNonRelevance += Math.max(0, raw[k]);
    }
  }

  const remainingWeight = 1.0 - clampedRelevance;
  const result: RankingWeights = { ...raw, relevance: clampedRelevance };

  if (sumNonRelevance <= 0) {
    const split = remainingWeight / (keys.length - 1);
    for (const k of keys) {
      if (k !== 'relevance') {
        result[k] = Math.round(split * 100) / 100;
      }
    }
  } else {
    for (const k of keys) {
      if (k !== 'relevance') {
        result[k] = Math.round(((Math.max(0, raw[k]) / sumNonRelevance) * remainingWeight) * 100) / 100;
      }
    }
  }

  // Adjust precision delta to ensure exact sum = 1.0
  const total =
    result.relevance +
    result.distance +
    result.price +
    result.reputation +
    result.stockFreshness +
    result.creditSupport;
  const delta = Math.round((1.0 - total) * 100) / 100;
  result.price = Math.max(0.05, Math.round((result.price + delta) * 100) / 100);

  return result;
}

export interface RankingExecutionLog {
  queryId: string;
  userId: string;
  planId: string;
  timestamp: string;
  activeWeights: RankingWeights;
  candidateCount: number;
  topShopName: string;
  topScore: number;
}

/**
 * Deterministic multi-feature weighted ranking engine
 * score(p) = sum_i w_i * f_i
 */
export function rankOffers(
  offers: ShopOffer[],
  userLocation: UserLocation,
  weights: RankingWeights,
  searchRelevanceMap?: Record<string, number>
): { ranked: RankedOffer[]; log: RankingExecutionLog } {
  if (offers.length === 0) {
    return {
      ranked: [],
      log: {
        queryId: `q-${Date.now()}`,
        userId: 'usr-persian-shopper',
        planId: 'plan-default',
        timestamp: new Date().toISOString(),
        activeWeights: weights,
        candidateCount: 0,
        topShopName: 'None',
        topScore: 0,
      },
    };
  }

  const sanitized = sanitizeWeights(weights);

  // 1. Compute dynamic distance based on user's current location
  const updatedOffers = offers.map((offer) => {
    const dist = calculateHaversineDistance(
      userLocation.lat,
      userLocation.lng,
      offer.coordinates.lat,
      offer.coordinates.lng
    );
    const drivingMins = Math.round(dist * 2.5 + 4);
    const walkingMins = Math.round(dist * 13);
    return {
      ...offer,
      distanceKm: dist,
      estimatedDrivingMins: drivingMins,
      estimatedWalkingMins: walkingMins,
    };
  });

  // 2. Extract raw features
  const rawRelevance = updatedOffers.map((o) =>
    searchRelevanceMap?.[o.id] ?? 0.9
  );
  const rawDistances = updatedOffers.map((o) => o.distanceKm);
  const rawPrices = updatedOffers.map((o) => o.price);
  const rawReputations = updatedOffers.map((o) => o.reputationScore);
  const rawFreshness = updatedOffers.map((o) => {
    // Verified via call gets highest score, recent update gets high score
    if (o.verificationCallLog) return 1.0;
    const hoursOld = (Date.now() - o.lastUpdatedTimestamp) / (3600 * 1000);
    if (hoursOld < 4) return 0.9;
    if (hoursOld < 24) return 0.7;
    return 0.4;
  });
  const rawCredit = updatedOffers.map((o) => {
    let s = 0.2;
    if (o.torobPayAccepted) s += 0.4;
    if (o.installmentOptions && o.installmentOptions.length > 0) s += 0.3;
    if (o.kallabargSupported) s += 0.1;
    return Math.min(1.0, s);
  });

  // 3. Normalize features
  const normRelevance = normalizeValues(rawRelevance, false);
  const normDistance = normalizeValues(rawDistances, true); // smaller distance = better (1.0)
  const normPrice = normalizeValues(rawPrices, true);       // smaller price = better (1.0)
  const normReputation = normalizeValues(rawReputations, false);
  const normFreshness = normalizeValues(rawFreshness, false);
  const normCredit = normalizeValues(rawCredit, false);

  // 4. Calculate weighted sum for each offer
  const calculated: RankedOffer[] = updatedOffers.map((offer, idx) => {
    const scores: NormalizedScores = {
      relevanceNorm: normRelevance[idx],
      distanceNorm: normDistance[idx],
      priceNorm: normPrice[idx],
      reputationNorm: normReputation[idx],
      stockFreshnessNorm: normFreshness[idx],
      creditSupportNorm: normCredit[idx],
      totalScore: 0,
    };

    const total =
      sanitized.relevance * scores.relevanceNorm +
      sanitized.distance * scores.distanceNorm +
      sanitized.price * scores.priceNorm +
      sanitized.reputation * scores.reputationNorm +
      sanitized.stockFreshness * scores.stockFreshnessNorm +
      sanitized.creditSupport * scores.creditSupportNorm;

    scores.totalScore = Math.round(total * 1000) / 1000;

    // Generate explainability rationale
    let explanation = '';
    const drivers: string[] = [];
    if (scores.priceNorm > 0.8) drivers.push('قیمت کف بازار و تخفیف ویژه');
    if (scores.distanceNorm > 0.75) drivers.push(`مسافت نزدیک (${offer.distanceKm} کیلومتر)`);
    if (scores.reputationNorm > 0.85) drivers.push('اعتبار ممتاز و سابقه بالا در ترب');
    if (offer.verificationCallLog) drivers.push('استعلام تلفنی موفق موجودی');
    if (offer.torobPayAccepted) drivers.push('پشتیبانی از ترب‌پی و اقساط');

    if (drivers.length > 0) {
      explanation = `برگزیده به علت: ${drivers.join(' · ')}`;
    } else {
      explanation = 'تعادل عمومی مناسب میان قیمت، دسترسی و شرایط فروشگاه';
    }

    return {
      offer,
      scores,
      rank: 1, // temporary
      explanation,
    };
  });

  // 5. Sort descending by total score
  calculated.sort((a, b) => b.scores.totalScore - a.scores.totalScore);

  // 6. Assign final ranks
  const ranked = calculated.map((item, index) => ({
    ...item,
    rank: index + 1,
  }));

  const log: RankingExecutionLog = {
    queryId: `q-${Date.now().toString(36)}`,
    userId: 'usr-persian-shopper',
    planId: 'plan-hybrid-v2',
    timestamp: new Date().toLocaleTimeString('fa-IR'),
    activeWeights: sanitized,
    candidateCount: ranked.length,
    topShopName: ranked[0]?.offer.shopName || '',
    topScore: ranked[0]?.scores.totalScore || 0,
  };

  return { ranked, log };
}
