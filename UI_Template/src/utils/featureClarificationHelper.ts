import { FeatureClarificationPayload, FeatureQuestion } from '../types';

/**
 * Helper to analyze user input and detect missing features required
 * by Torob's in-person algorithm (Timing, Proximity, Payment, Usage/Budget).
 */
export function analyzeUserQueryForFeatures(query: string): FeatureClarificationPayload | null {
  const q = query.toLowerCase().trim();

  // If the query is already an explicit follow-up or command, skip clarification
  if (
    q.startsWith('استعلام تلفنی') ||
    q.startsWith('فروشگاه‌های باز') ||
    q.startsWith('آدرس فروشگاه') ||
    q.startsWith('تست سایز') ||
    q.length < 3
  ) {
    return null;
  }

  // Detect category
  let category = 'عمومی';
  let categoryTitle = 'کالای انتخابی شما';

  if (q.includes('اسکوتر') || q.includes('scooter')) {
    category = 'اسکوتر برقی';
    categoryTitle = 'اسکوتر برقی';
  } else if (
    q.includes('گوشی') ||
    q.includes('موبایل') ||
    q.includes('آیفون') ||
    q.includes('سامسونگ') ||
    q.includes('phone')
  ) {
    category = 'گوشی موبایل';
    categoryTitle = 'گوشی موبایل';
  } else if (
    q.includes('کتونی') ||
    q.includes('کفش') ||
    q.includes('نایک') ||
    q.includes('پیاده‌روی')
  ) {
    category = 'کفش و کتونی';
    categoryTitle = 'کفش و کتونی ورزشی';
  }

  // Check if features are already specified in the user's initial prompt
  const hasTiming = /(امروز|الان|فردا|جمعه|عصر|سریع|شنبه|هفته|ساعت)/.test(q);
  const hasProximity = /(نزدیک|چارسو|جمهوری|علاءالدین|پالادیوم|کوروش|غرب|شمال|کیلومتر|بازار|پایتخت)/.test(q);
  const hasPayment = /(قسط|اقساط|ترب‌پی|ترب پی|نقد|چک|اسنپ|اعتباری)/.test(q);
  const hasUsage = /(شیب|میلیون|تومان|بودجه|وزن|سبک|عکاسی|دوربین|طبی|باتری|دانشجو)/.test(q);

  const providedCount = [hasTiming, hasProximity, hasPayment, hasUsage].filter(Boolean).length;

  // If user provided fewer than 3 features, we generate the tailored questions
  if (providedCount >= 3) {
    return null;
  }

  // Construct questions tailored to category
  let questions: FeatureQuestion[] = [];

  if (category === 'اسکوتر برقی') {
    questions = [
      {
        id: 'timing',
        title: 'زمان خرید حضوری',
        question: 'کی قصد مراجعه به فروشگاه و خرید حضوری اسکوتر دارید؟',
        impactBadge: 'اثر بر باز بودن فروشگاه و موجودی انبار',
        iconType: 'time',
        options: [
          'همین امروز عصر (فروشگاه‌های الان باز)',
          'فردا یا آخر هفته',
          'فعلاً بررسی قیمت و مدل‌ها',
        ],
        placeholder: 'مثلاً: فردا بعدازظهر حوالی ساعت ۵ تا ۶...',
      },
      {
        id: 'proximity',
        title: 'اولویت مکانی در تهران',
        question: 'نزدیک‌ترین فروشگاه به شما اولویت دارد یا مراکز بورس بازار؟',
        impactBadge: 'اثر بر رتبه‌بندی نقشه و فاصله',
        iconType: 'location',
        options: [
          'نزدیک‌ترین فروشگاه به من (زیر ۵ کیلومتر)',
          'مرکز تخصصی چارسو و جمهوری',
          'بهترین قیمت در هر کجای تهران',
        ],
        placeholder: 'مثلاً: حوالی میدان ولیعصر یا دسترسی آسان با مترو...',
      },
      {
        id: 'payment',
        title: 'شیوه تسویه و پرداخت',
        question: 'نحوه پرداخت مد نظرتان در فروشگاه چگونه است؟',
        impactBadge: 'فیلتر پذیرندگان ترب‌پی و اقساطی',
        iconType: 'payment',
        options: [
          'کارت بانکی / نقدی در مغازه',
          'اقساطی با ترب‌پی (بدون ضامن)',
          'خرید اعتباری یا چکی',
        ],
        placeholder: 'توضیح دلخواه درباره شرایط پرداخت یا بودجه شما...',
      },
      {
        id: 'usage',
        title: 'کاربرد اصلی و شیب مسیر',
        question: 'مسیر تردد روزمره شما چطور است و چه قدرتی نیاز دارید؟',
        impactBadge: 'انتخاب توان موتور و ترمز',
        iconType: 'usage',
        options: [
          'مسیرهای مسطح شهری (روزمره تا ۳۵ میلیون)',
          'مسیرهای شیب‌دار و برد بالا (بالای ۴۰ میلیون)',
          'سبک‌وزن جهت حمل در مترو و اتوبوس',
        ],
        placeholder: 'مثلاً: مسیر شیب‌دار ونک به تجریش، وزن ۸۵ کیلو...',
      },
    ];
  } else if (category === 'گوشی موبایل') {
    questions = [
      {
        id: 'timing',
        title: 'زمان خرید حضوری',
        question: 'چه زمانی قصد مراجعه به بازار موبایل و خرید حضوری دارید؟',
        impactBadge: 'استعلام نوسان ارز و پارت‌نامبر',
        iconType: 'time',
        options: [
          'همین امروز عصر',
          'طی چند روز آینده',
          'صرفاً استعلام قیمت و مقایسه',
        ],
        placeholder: 'مثلاً: امروز بعد از ساعات کاری...',
      },
      {
        id: 'proximity',
        title: 'مرکز خرید مدنظر',
        question: 'کدام بورس موبایل تهران برای مراجعه شما مناسب‌تر است؟',
        impactBadge: 'فیلتر دسترسی پاساژها و طرح ترافیک',
        iconType: 'location',
        options: [
          'بازار چارسو و علاءالدین (جمهوری)',
          'پاساژ پایتخت (میرداماد / ونک)',
          'نزدیک‌ترین فروشگاه معتبر به موقعیت من',
        ],
        placeholder: 'مثلاً: غرب تهران حوالی کوروش یا مرکز شهر...',
      },
      {
        id: 'payment',
        title: 'نحوه پرداخت و فاکتور',
        question: 'شیوه پرداخت مد نظر شما در فروشگاه چیست؟',
        impactBadge: 'فیلتر فاکتور رسمی و خرید اقساطی',
        iconType: 'payment',
        options: [
          'پرداخت نقدی با فاکتور رسمی و رجیستری',
          'خرید اقساطی با ترب‌پی (بدون پیش‌پرداخت)',
          'طرح تعویض گوشی کارکرده با نو',
        ],
        placeholder: 'توضیحات دلخواه پیرامون پرداخت...',
      },
      {
        id: 'usage',
        title: 'اولویت کاربری و بودجه',
        question: 'مهم‌ترین اولویت فنی شما در این گوشی چیست؟',
        impactBadge: 'انتخاب پردازنده، دوربین و باتری',
        iconType: 'usage',
        options: [
          'دوربین پرچمدار و تولید محتوا',
          'باتری قوی و استفاده روزمره کاری',
          'گیمینگ سنگین و پردازش بالا',
        ],
        placeholder: 'مثلاً: دوربین عالی تا سقف ۶۰ میلیون تومان...',
      },
    ];
  } else if (category === 'کفش و کتونی') {
    questions = [
      {
        id: 'timing',
        title: 'زمان تست حضوری سایز',
        question: 'کی قصد مراجعه به فروشگاه جهت تست پا و خرید دارید؟',
        impactBadge: 'هماهنگی موجودی نیم‌سایز در انبار',
        iconType: 'time',
        options: [
          'همین امروز عصر (تست فوری)',
          'آخر هفته (پنج‌شنبه یا جمعه)',
          'بررسی مدل‌ها و استعلام قیمت',
        ],
        placeholder: 'زمان مناسب خود را بنویسید...',
      },
      {
        id: 'proximity',
        title: 'مرکز خرید انتخابی',
        question: 'کدام مجتمع تجاری تهران برای خرید حضوری شما در دسترس‌تر است؟',
        impactBadge: 'رتبه‌بندی شعب رسمی برندها',
        iconType: 'location',
        options: [
          'پالادیوم (زعفرانیه / شمال تهران)',
          'کوروش‌مال (بزرگراه ستاری / غرب تهران)',
          'میدان ولیعصر و بازار بزرگ',
        ],
        placeholder: 'مثلاً: سعادت‌آباد یا شرق تهران...',
      },
      {
        id: 'payment',
        title: 'شیوه پرداخت',
        question: 'روش پرداخت مد نظر شما در نمایندگی چگونه است؟',
        impactBadge: 'فیلتر ضمانت تعویض و ترب‌پی',
        iconType: 'payment',
        options: [
          'کارت‌خوان مغازه با ضمانت تعویض سایز',
          'اعتباری با ترب‌پی',
          'استفاده از تخفیف جشنواره حضوری',
        ],
        placeholder: 'توضیح دلخواه...',
      },
      {
        id: 'usage',
        title: 'نوع کاربری و هدف استفاده',
        question: 'کتونی را عمدتاً برای چه نوع استفاده‌ای می‌خواهید؟',
        impactBadge: 'انتخاب فوم زیره و فیت پا',
        iconType: 'usage',
        options: [
          'پیاده‌روی روزمره و رفع کمردرد',
          'دویدن و تمرینات سرعتی ورزشی',
          'کتونی استایل شهری و اداری',
        ],
        placeholder: 'مثلاً: کفی طبی برای استفاده طولانی در بیمارستان...',
      },
    ];
  } else {
    questions = [
      {
        id: 'timing',
        title: 'زمان خرید حضوری',
        question: 'کی قصد خرید حضوری و مراجعه به فروشگاه در تهران را دارید؟',
        impactBadge: 'ساعات کاری و موجودی لحظه‌ای مغازه',
        iconType: 'time',
        options: [
          'همین امروز عصر',
          'طی ۲ تا ۳ روز آینده',
          'فعلاً بررسی و مشاوره اولیه',
        ],
        placeholder: 'زمان حدودی مد نظر خود را بنویسید...',
      },
      {
        id: 'proximity',
        title: 'اولویت مکانی و فاصله',
        question: 'کدام محدوده تهران برای مراجعه حضوری شما ترجیح دارد؟',
        impactBadge: 'رتبه‌بندی نقشه و مسافت تا مغازه',
        iconType: 'location',
        options: [
          'نزدیک‌ترین فروشگاه به موقعیت من',
          'مراکز بورس و پاساژهای تخصصی',
          'فرقی ندارد؛ بهترین قیمت اولویت دارد',
        ],
        placeholder: 'نام منطقه یا خیابان مد نظر خود را بنویسید...',
      },
      {
        id: 'payment',
        title: 'شیوه پرداخت و تسویه',
        question: 'روش پرداخت ترجیحی شما در مغازه چیست؟',
        impactBadge: 'فیلتر فروشگاه‌های دارای ترب‌پی یا اقساط',
        iconType: 'payment',
        options: [
          'پرداخت کارت بانکی یا نقدی',
          'خرید اقساطی ترب‌پی (بدون چک)',
          'خرید اعتباری یا چکی',
        ],
        placeholder: 'توضیح دلخواه درباره بودجه یا پرداخت...',
      },
      {
        id: 'usage',
        title: 'بودجه و انتظار اصلی',
        question: 'سقف بودجه یا اولویت اصلی شما در انتخاب این محصول چیست؟',
        impactBadge: 'انتخاب بهترین مدل فنی و ارزش خرید',
        iconType: 'usage',
        options: [
          'بهترین کارایی با قیمت اقتصادی',
          'مدل پرچمدار و بالاترین کیفیت بازار',
          'مدل متوسط با بیشترین رضایت خریداران',
        ],
        placeholder: 'مثلاً: سقف بودجه تا ۳۰ میلیون تومان...',
      },
    ];
  }

  return {
    category,
    categoryTitle,
    questions,
    isSubmitted: false,
  };
}
