import {render,screen,waitFor} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import DocumentEvidencePane from './DocumentEvidencePane';
import {EvidenceProvider,useEvidence} from './EvidenceContext';
import {fetchApplicationDocument} from '../services/applicationsApi';
jest.mock('../services/applicationsApi',()=>({fetchApplicationDocument:jest.fn()}));
const hash='a'.repeat(64);
const layout={file_sha256:hash,pages:[{number:1,width:100,height:200,coordinate_space:'unrotated_crop_points'}]};
const response={page:1,pages:1,width:100,height:200,file_sha256:hash,coordinate_space:'unrotated_crop_points',image:'data:image/png;base64,AA=='};
function Selector(){const context=useEvidence();return <button onClick={()=>context?.select({text:'Synthetic evidence',page:1,bbox:[10,20,30,40]})}>انتخاب شاهد آزمایشی</button>}
beforeEach(()=>jest.mocked(fetchApplicationDocument).mockResolvedValue(response));

test('سند تا انتخاب کاربر واکشی نمی‌شود و مختصات هم‌نسخه هایلایت می‌شوند',async()=>{
  render(<EvidenceProvider><Selector/><DocumentEvidencePane applicationId="application-only" layout={layout}/></EvidenceProvider>);
  expect(fetchApplicationDocument).not.toHaveBeenCalled();
  await userEvent.click(screen.getByText('انتخاب شاهد آزمایشی'));
  expect(await screen.findByTestId('evidence-highlight')).toHaveStyle({left:'10%',top:'10%',width:'20%',height:'10%'});
  expect(fetchApplicationDocument).toHaveBeenCalledWith('application-only',1,hash,expect.any(AbortSignal));
});

test('نسخه نامنطبق هیچ هایلایتی ندارد و شکست سند شاهد متن را حذف نمی‌کند',async()=>{
  jest.mocked(fetchApplicationDocument).mockResolvedValue({...response,file_sha256:'b'.repeat(64)});
  render(<EvidenceProvider><Selector/><DocumentEvidencePane applicationId="a" layout={layout}/></EvidenceProvider>);
  await userEvent.click(screen.getByText('انتخاب شاهد آزمایشی'));
  await screen.findByRole('img');
  expect(screen.queryByTestId('evidence-highlight')).not.toBeInTheDocument();
  jest.mocked(fetchApplicationDocument).mockRejectedValue(new Error('unavailable'));
  await userEvent.click(screen.getByText('بستن پیش‌نمایش'));
  await userEvent.click(screen.getByText('نمایش PDF'));
  await waitFor(()=>expect(screen.getByRole('alert')).toHaveTextContent('پیش‌نمایش دریافت نشد'));
  expect(screen.getByText('Synthetic evidence')).toBeInTheDocument();
});
