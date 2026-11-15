const views = {
  interface: {
    alt: 'Zf2Lumix 胶片队列，包含照片、输出目录、颜色校准旋钮和转换键',
    caption: '导入、拖放、多选。照片与边字一起滚动。',
    label: '胶片队列',
  },
  converting: {
    alt: '实际转换中的 Zf2Lumix，机械指针与 LCD 显示处理进度',
    caption: '转换键保持下沉，胶片随当前照片前进。',
    label: '转换进度',
  },
  records: {
    alt: '纸质冲印记录，显示批次编号、处理结果和三列照片清单',
    caption: '点开纸签，查看整批照片与逐张结果。',
    label: '冲印记录',
  },
  detail: {
    alt: '单张检片详情，显示照片预览、源文件、状态与输出',
    caption: '查看照片与文件记录，返回清单或定位回胶片。',
    label: '检片详情',
  },
};

const screen = document.querySelector('#screen');
const screenLink = document.querySelector('#screen-link');
const caption = document.querySelector('#view-caption');
const viewButtons = [...document.querySelectorAll('[data-view]')];

for (const button of viewButtons) {
  button.addEventListener('click', () => {
    const view = views[button.dataset.view];
    screen.src = `assets/${button.dataset.view}.png`;
    screen.alt = view.alt;
    screenLink.href = screen.src;
    screenLink.setAttribute('aria-label', `打开${view.label}原图`);
    caption.textContent = view.caption;
    for (const item of viewButtons) {
      item.setAttribute('aria-pressed', String(item === button));
    }
  });
}
