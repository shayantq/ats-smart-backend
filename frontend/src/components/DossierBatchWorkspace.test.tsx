import {render, screen, within} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {QueryClient, QueryClientProvider} from '@tanstack/react-query';
import DossierBatchWorkspace from './DossierBatchWorkspace';
import {fetchApplicationPage} from '../services/applicationsApi';
import {compareDossiers, createReanalysisBatch, getBatch,recoverBatch} from '../services/dossierReviewApi';
import type {ApplicationListItem} from '../types/application';

jest.mock('../services/applicationsApi',()=>({fetchApplicationPage:jest.fn()}));
jest.mock('../services/dossierReviewApi',()=>({compareDossiers:jest.fn(),createReanalysisBatch:jest.fn(),getBatch:jest.fn(),recoverBatch:jest.fn()}));
jest.mock('./CandidateDossier',()=>()=>null);

const item=(id:string):ApplicationListItem=>({application_id:id,candidate_id:id,candidate_name:`Synthetic ${id}`,current_status:'Draft',score_ai:null,updated_at:'2026-11-16T00:00:00Z'});
function mount(){
  const client=new QueryClient({defaultOptions:{queries:{retry:false}}});
  return render(<QueryClientProvider client={client}><DossierBatchWorkspace jobId="job"/></QueryClientProvider>);
}

test('انتخاب میان صفحات حفظ می‌شود و هیچ تحلیل مجددی خودکار شروع نمی‌شود',async()=>{
  jest.mocked(fetchApplicationPage).mockImplementation(async(_job,_status,cursor)=>({items:[item(cursor?'b':'a')],next_cursor:cursor?null:'next',previous_cursor:null,has_next:!cursor,has_previous:!!cursor}));
  jest.mocked(compareDossiers).mockResolvedValue({items:[],comparable:false,ranked:false});
  mount();
  await userEvent.click(await screen.findByLabelText('Synthetic a'));
  await userEvent.click(screen.getByRole('button',{name:'صفحهٔ بعد فهرست'}));
  await userEvent.click(await screen.findByLabelText('Synthetic b'));
  await userEvent.click(screen.getByRole('button',{name:'مقایسهٔ شواهد منتخب‌ها'}));
  await screen.findByRole('heading',{name:'مقایسهٔ مستند'});
  expect(compareDossiers).toHaveBeenCalledWith(['a','b']);
  expect(createReanalysisBatch).not.toHaveBeenCalled();
});

test('فیلتر مجهول و شاهد متنی بدون ساختن رتبه یا امتیاز نمایش داده می‌شوند',async()=>{
  jest.mocked(fetchApplicationPage).mockResolvedValue({items:[item('a'),item('b')],next_cursor:null,previous_cursor:null,has_next:false,has_previous:false});
  jest.mocked(compareDossiers).mockResolvedValue({comparable:false,ranked:false,items:[
    {application_id:'a',complete:true,requirements:[{text:'Python',status:'met',evidence:[{text:'Built Python APIs'}]}]},
    {application_id:'b',complete:false,requirements:[{text:'Docker',status:'unknown',evidence:[]}]},
  ]});
  mount();
  await userEvent.click(await screen.findByLabelText('Synthetic a'));
  await userEvent.click(screen.getByLabelText('Synthetic b'));
  await userEvent.click(screen.getByRole('button',{name:'مقایسهٔ شواهد منتخب‌ها'}));
  const comparison=(await screen.findByRole('heading',{name:'مقایسهٔ مستند'})).closest('section')!;
  expect(within(comparison).getByText(/رتبه‌بندی عددی معتبر نیست/)).toBeInTheDocument();
  await userEvent.click(within(comparison).getByText('شواهد شرط'));
  expect(within(comparison).getByText('Built Python APIs')).toBeVisible();
  await userEvent.selectOptions(screen.getByLabelText('فیلتر شواهد'),'unknown');
  expect(within(comparison).queryByRole('heading',{name:'Synthetic a'})).not.toBeInTheDocument();
  expect(within(comparison).getByRole('heading',{name:'Synthetic b'})).toBeInTheDocument();
});

test('با شروع تحلیل مجدد، مقایسهٔ قدیمی به‌عنوان نتیجهٔ جدید باقی نمی‌ماند',async()=>{
  jest.mocked(fetchApplicationPage).mockResolvedValue({items:[item('a')],next_cursor:null,previous_cursor:null,has_next:false,has_previous:false});
  jest.mocked(compareDossiers).mockResolvedValue({items:[],comparable:false,ranked:false});
  jest.mocked(createReanalysisBatch).mockResolvedValue({batch_id:'batch',items:{}});
  jest.mocked(getBatch).mockResolvedValue({items:[{application_id:'a',processing:{status:'succeeded'},queue:{reason:'queued'}}]});
  mount();
  await userEvent.click(await screen.findByLabelText('Synthetic a'));
  await userEvent.click(screen.getByRole('button',{name:'مقایسهٔ شواهد منتخب‌ها'}));
  await screen.findByRole('heading',{name:'مقایسهٔ مستند'});
  await userEvent.click(screen.getByRole('button',{name:'صف‌گیری تحلیل مجدد منتخب‌ها'}));
  await screen.findByRole('heading',{name:'پیشرفت تحلیل گروه'});
  expect(screen.queryByRole('heading',{name:'مقایسهٔ مستند'})).not.toBeInTheDocument();
  expect(createReanalysisBatch).toHaveBeenCalledWith(['a']);
});

test('بازیابی فقط با دکمه و مجوز اعلام‌شدهٔ نویسنده درخواست می‌شود',async()=>{
  jest.mocked(fetchApplicationPage).mockResolvedValue({items:[item('a')],next_cursor:null,previous_cursor:null,has_next:false,has_previous:false});
  jest.mocked(createReanalysisBatch).mockResolvedValue({batch_id:'recoverable',items:{}});
  jest.mocked(getBatch).mockResolvedValue({can_recover:true,items:[{application_id:'a',processing:{status:'failed'},queue:{reason:'queue_unavailable'}}]});
  jest.mocked(recoverBatch).mockResolvedValue({batch_id:'recoverable'});
  mount();
  await userEvent.click(await screen.findByLabelText('Synthetic a'));
  await userEvent.click(screen.getByRole('button',{name:'صف‌گیری تحلیل مجدد منتخب‌ها'}));
  const button=await screen.findByRole('button',{name:'بازیابی ارسال‌های ناتمام گروه'});
  expect(recoverBatch).not.toHaveBeenCalled();
  await userEvent.click(button);
  expect(recoverBatch).toHaveBeenCalledWith('recoverable');
});
