import {render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import DossierHumanReview from './DossierHumanReview';
import {addReviewEvent,getVersions,compareVersions,type ReviewState} from '../services/dossierReviewApi';
import {ApiError} from '../services/apiClient';
jest.mock('../services/dossierReviewApi',()=>({addReviewEvent:jest.fn(),getVersions:jest.fn().mockResolvedValue({items:[]}),compareVersions:jest.fn()}));
const state:ReviewState={application_id:'a',revision:0,source_hash:'a'.repeat(64),effective_parsed:{},targets:[{target:'identity.name',anchor:'b'.repeat(64),original:{value:'MIRA HART'}}],events:[],notes:[],corrections:[],shortlisted:false,sections:{}};

test('یادداشت به‌طور پیش‌فرض خصوصی است و بدون پاسخ موفق ذخیره‌شده اعلام نمی‌شود',async()=>{
  jest.mocked(addReviewEvent).mockRejectedValue(new ApiError('conflict',409));
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  render(<QueryClientProvider client={client}><DossierHumanReview applicationId="a" state={state}/></QueryClientProvider>);
  await userEvent.click(screen.getByText('یادداشت و بازخورد'));
  await userEvent.type(screen.getByLabelText('متن یادداشت'),'Synthetic private note');
  await userEvent.click(screen.getByText('ذخیره یادداشت'));
  expect(await screen.findByRole('alert')).toHaveTextContent('ذخیره انجام نشد');
  expect(screen.queryByText('بازبینی در سرور ذخیره شد.')).not.toBeInTheDocument();
  expect(addReviewEvent).toHaveBeenCalledWith('a',expect.objectContaining({visibility:'private',action:'note'}));
});

test('فرم بازشده revision قدیمی را پس از تغییر همکار به نسخه تازه تبدیل نمی‌کند',async()=>{
  jest.mocked(addReviewEvent).mockResolvedValue({...state,revision:2});
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  const view=(current:ReviewState)=><QueryClientProvider client={client}><DossierHumanReview applicationId="a" state={current}/></QueryClientProvider>;
  const rendered=render(view(state));
  await userEvent.type(screen.getByLabelText('دلیل ثبت یا اصلاح'),'Verified source');
  rendered.rerender(view({...state,revision:1}));
  await userEvent.click(screen.getByText('اصلاح مستند یک فیلد'));
  await userEvent.selectOptions(screen.getByLabelText('فیلد منبع'),'identity.name');
  await userEvent.type(screen.getByLabelText('مقدار تصحیح‌شده'),'Mira Hart');
  await userEvent.type(screen.getByLabelText('شاهد متنی یا توضیح محل بررسی در سند'),'Visual source');
  await userEvent.click(screen.getByText('ثبت اصلاح انسانی'));
  await screen.findByText('بازبینی در سرور ذخیره شد.');
  expect(addReviewEvent).toHaveBeenLastCalledWith('a',expect.objectContaining({expected_revision:0,action:'correction'}));
});

test('مقایسهٔ نسخه‌ها مقدار قبلی و بعدی و شاهد را با مرز اعتبار نمایش می‌دهد',async()=>{
  jest.mocked(getVersions).mockResolvedValue({items:['v1','v2'].map(id=>({id,created_at:'2026-11-16T10:00:00Z',source_hash:'a',analysis_version:'evidence-v2',job_sha256:'job'}))});
  jest.mocked(compareVersions).mockResolvedValue({comparable:false,changed:['job_sha256'],changed_sections:['identity'],score_delta:null,field_changes:[{label:'نام فایل',before:{value:'OLD',evidence:['Source before']},after:{value:'NEW',evidence:['Source after']}}]});
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  render(<QueryClientProvider client={client}><DossierHumanReview applicationId="a" state={state}/></QueryClientProvider>);
  await userEvent.click(screen.getByText('تاریخچهٔ ثبت‌ها و نسخه‌های تحلیل'));
  await userEvent.selectOptions(await screen.findByLabelText('نسخهٔ اول'),'v1');
  await userEvent.selectOptions(screen.getByLabelText('نسخهٔ دوم'),'v2');
  await userEvent.click(screen.getByRole('button',{name:'مقایسهٔ دو نسخه'}));
  expect(await screen.findByText(/مقایسهٔ عددی معتبر نیست/)).toBeVisible();
  expect(screen.getByText('OLD')).toBeVisible();expect(screen.getByText('NEW')).toBeVisible();
  expect(screen.getByText('Source before')).toBeVisible();
  expect(screen.queryByText(/اختلاف امتیاز پیش‌بینی ثبت‌شده/)).not.toBeInTheDocument();
});
