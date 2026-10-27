import fs from 'node:fs/promises';
import {Workbook,SpreadsheetFile} from '@oai/artifact-tool';
const [input,output,preview]=process.argv.slice(2);
const data=JSON.parse(await fs.readFile(input,'utf8'));
const wb=Workbook.create();const sheet=wb.worksheets.add('生产明细');
const matrix=[['Article','Size','TXT1','TXT2','Barcode','Quantity']];
let last='';
for(const r of data.rows){
 const group=r.txt1+'|'+r.txt2.replace(/-[^-]*$/,'');
 if(last&&last!==group)matrix.push([null,null,null,null,null,null]);
 matrix.push([r.article,r.size,r.txt1,r.txt2,String(r.barcode),r.quantity]);last=group;
}
sheet.getRange(`A1:F${matrix.length}`).values=matrix;
sheet.getRange(`A1:F${matrix.length}`).format.font={name:'Arial',size:11};
sheet.getRange(`A1:F${matrix.length}`).format.rowHeight=21;
sheet.getRange(`A1:F${matrix.length}`).format.borders={preset:'all',style:'thin',color:'#DEE4EB'};
sheet.getRange('A1:F1').format.fill='#416FBE';sheet.getRange('A1:F1').format.font={bold:true,color:'#FFFFFF',name:'Arial',size:11};
sheet.getRange('A1:F1').format.rowHeight=27;
for(const [col,width] of [['A',20],['B',9],['C',24],['D',48],['E',24],['F',13]])sheet.getRange(`${col}1:${col}${matrix.length}`).format.columnWidth=width;
sheet.getRange(`B2:B${matrix.length}`).setNumberFormat('@');sheet.getRange(`E2:E${matrix.length}`).setNumberFormat('0');sheet.getRange(`F2:F${matrix.length}`).setNumberFormat('0');
sheet.getRange('H1').values=[['来源：'+data.source]];sheet.getRange('H1').format.columnWidth=65;sheet.getRange('H1').format.font={name:'Arial',size:10,color:'#64748B'};
sheet.freezePanes.freezeRows(1);sheet.freezePanes.freezeColumns(3);sheet.showGridLines=false;
const out=await SpreadsheetFile.exportXlsx(wb);await out.save(output);
if(preview){const blob=await wb.render({sheetName:'生产明细',range:'A1:F20',scale:1.5});await fs.writeFile(preview,new Uint8Array(await blob.arrayBuffer()));}
console.log(JSON.stringify({rows:data.rows.length,output}));
