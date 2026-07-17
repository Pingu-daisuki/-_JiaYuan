import { PresentationFile, FileBlob } from "@oai/artifact-tool";

const input = process.argv[2];
const presentation = await PresentationFile.importPptx(await FileBlob.load(input));
const slide = presentation.slides.items[10];
const shapes = slide.shapes.items;
const target = shapes.find((shape) => shape.name === "retrieval-body-0") || shapes.find((shape) => shape.name === "ingest-body-0");
const before = String(target.text);
target.text = "账号 / 轮询间隔\n时间段 / 人数阈值";
console.log(JSON.stringify({
  slideCount: presentation.slides.items.length,
  shapeCount: shapes.length,
  names: shapes.map((shape) => shape.name),
  targetKeys: Object.keys(target || {}),
  textKeys: Object.keys(target?.text || {}),
  before,
  textString: String(target?.text),
  textValue: target?.text?.text,
}, null, 2));
