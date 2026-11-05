import { ShopOffer } from '../types';

export interface CallSimulationStep {
  speaker: 'ایجنت ترب' | 'فروشنده مغازه';
  text: string;
  delayMs: number;
}

export function generateCallScript(offer: ShopOffer): CallSimulationStep[] {
  return [
    {
      speaker: 'ایجنت ترب',
      text: `سلام و وقت‌بخیر از دستیار هوشمند ترب تماس می‌گیرم. می‌خواستم موجودی و قیمت قطعی امروز ${offer.productId === 'p-scooter-1' ? 'اسکوتر برقی شیائومی 4 Pro' : 'محصول انتخابی'} رو برای مشتری خرید حضوری استعلام بگیرم.`,
      delayMs: 1400,
    },
    {
      speaker: 'فروشنده مغازه',
      text: `سلام، بله خوشبختانه موجود داریم. قیمت کف امروز با گارانتی معتبر ${(offer.price).toLocaleString('fa-IR')} تومان تقدیمتون می‌کنیم. جنس آکبند با پلمپ اصلی هست.`,
      delayMs: 2200,
    },
    {
      speaker: 'ایجنت ترب',
      text: `بسیار عالی. آدرس واحد داخل ${offer.mallName} در ${offer.mallFloor}، ${offer.mallUnit} (${offer.mallNote}) هست درسته؟ و ساعت کاری امروز تا چه زمانیه؟`,
      delayMs: 2000,
    },
    {
      speaker: 'فروشنده مغازه',
      text: `بله دقیقاً همین لوکیشنه. امروز تا ساعت ${offer.workingHours.split('الی')[1] || '۲۱:۳۰'} یکسره باز هستیم و امکان تست اولیه و کارت‌خوان ترب‌پی هم فعاله. تشریف بیارید در خدمتیم.`,
      delayMs: 2400,
    },
    {
      speaker: 'ایجنت ترب',
      text: 'بسیار متشکرم از پاسخگویی دقیق و زمانتون. مشخصات تأیید و برای کاربر ثبت شد. روز خوبی داشته باشید.',
      delayMs: 1600,
    },
  ];
}
