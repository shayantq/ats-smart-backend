import {render,screen} from '@testing-library/react';
import EvidenceAnalysisPanel from './EvidenceAnalysisPanel';

test('نبود شاهد ناتوانی تلقی نمی‌شود و پوشش با امتیاز استخدام متفاوت است',()=>{
  render(<EvidenceAnalysisPanel value={{version:'evidence-analysis-v1',skills:[],requirements:[{text:'Java',priority:'required',status:'unknown',evidence:[]}],coverage:{lower:0,upper:100}}}/>);
  expect(screen.getByText(/ضروری — نامشخص/)).toBeInTheDocument();
  expect(screen.getByText(/حد بالا شامل شروط نامشخص/)).toBeInTheDocument();
  expect(screen.getByText(/تصمیم استخدام نیست/)).toBeInTheDocument();
});

test('استنباط و اشاره در گواهی‌نامه به تجربه عملی تبدیل نمی‌شوند',()=>{
  render(<EvidenceAnalysisPanel value={{version:'evidence-analysis-v1',skills:[{name:'Python',basis:'inferred',observations:[{context:'certifications',evidence:[{text:'FastAPI Certificate'}]}]}],requirements:[],coverage:{}}}/>);
  expect(screen.getByText(/استنباط از مهارت مرتبط/)).toBeInTheDocument();
  expect(screen.getByText(/تجربهٔ عملی اثبات نمی‌شود/)).toBeInTheDocument();
});

test('تغییر سمت و نتیجه تیم بدون ادعای ارتقای قطعی نمایش داده می‌شوند',()=>{
  const claim={value:'Our team served 10000 users',status:'attributed',evidence:[{text:'Our team served 10000 users'}]};
  render(<EvidenceAnalysisPanel value={{version:'evidence-analysis-v2.1',skills:[],requirements:[],transitions:[{kind:'same_employer_role_change'}],achievements:[{claim,individual_contribution:'team_claim'}]}}/>);
  expect(screen.getByText(/ارتقا از این تغییر به‌تنهایی اثبات نمی‌شود/)).toBeInTheDocument();
  expect(screen.getByText(/سهم فرد مشخص نشده است/)).toBeInTheDocument();
});
