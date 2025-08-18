/**
 * 甘特图JavaScript逻辑
 */

class GanttChart {
    constructor() {
        this.currentDate = new Date();
        this.startDate = new Date();
        this.endDate = new Date();
        this.devices = [];
        this.rentals = [];
        this.selectedCell = null;
        this.rentalStartDate = null;
        
        this.init();
    }
    
    init() {
        this.setupDateRange();
        this.loadData();
        this.setupEventListeners();
        this.initRegionSelectors();
        this.updateStats();
    }
    
    setupDateRange() {
        // 设置默认显示当前月
        const today = new Date();
        this.startDate = new Date(today.getFullYear(), today.getMonth(), 1);
        this.endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        this.currentDate = today;
        
        this.updateDateNavigation();
    }
    
    setupEventListeners() {
        // 设置日期输入框的默认值
        document.getElementById('query-start-date').value = this.formatDate(this.startDate);
        document.getElementById('query-end-date').value = this.formatDate(this.endDate);
        
        // 设置添加租赁模态框的日期
        document.getElementById('start-date').value = this.formatDate(new Date());
        document.getElementById('end-date').value = this.formatDate(new Date(Date.now() + 7 * 24 * 60 * 60 * 1000));
    }
    
    async loadData() {
        try {
            const response = await axios.get('/api/gantt/data', {
                params: {
                    start_date: this.formatDate(this.startDate),
                    end_date: this.formatDate(this.endDate)
                }
            });
            
            if (response.data.success) {
                this.devices = response.data.data.devices;
                this.rentals = response.data.data.rentals;
                this.renderGantt();
                this.updateStats();
                this.populateFilters();
            } else {
                console.error('加载数据失败:', response.data.error);
            }
        } catch (error) {
            console.error('加载数据异常:', error);
        }
    }
    
    renderGantt() {
        const container = document.getElementById('gantt-chart');
        container.innerHTML = '';
        
        // 创建甘特图
        this.createHeader(container);
        this.createRows(container);
    }
    
    createHeader(container) {
        const header = document.createElement('div');
        header.className = 'gantt-header';
        
        const headerRow = document.createElement('div');
        headerRow.className = 'gantt-row';
        
        // 设备列标题
        const deviceHeader = document.createElement('div');
        deviceHeader.className = 'gantt-cell gantt-device-cell';
        deviceHeader.innerHTML = '<strong>设备</strong>';
        headerRow.appendChild(deviceHeader);
        
        // 日期列标题
        const currentDate = new Date(this.startDate);
        while (currentDate <= this.endDate) {
            const dateHeader = document.createElement('div');
            dateHeader.className = 'gantt-cell gantt-date-cell';
            
            // 检查是否是今天
            if (this.isToday(currentDate)) {
                dateHeader.className += ' gantt-today';
            }
            
            dateHeader.innerHTML = `
                <div>${this.formatDateHeader(currentDate)}</div>
            `;
            headerRow.appendChild(dateHeader);
            
            currentDate.setDate(currentDate.getDate() + 1);
        }
        
        header.appendChild(headerRow);
        container.appendChild(header);
    }
    
    createRows(container) {
        this.devices.forEach(device => {
            const row = document.createElement('div');
            row.className = 'gantt-row';
            
            // 设备信息列
            const deviceCell = document.createElement('div');
            deviceCell.className = 'gantt-cell gantt-device-cell';
            deviceCell.innerHTML = `
                <div>
                    <div><strong>${device.name}</strong></div>
                    <div style="font-size: 0.8em; color: #6c757d;">
                        编号: ${device.serial_number || 'N/A'}
                    </div>
                    <div style="font-size: 0.8em; color: #6c757d;">
                        位置: ${device.location || 'N/A'} | 状态: ${this.getStatusText(device.status)}
                    </div>
                </div>
            `;
            row.appendChild(deviceCell);
            
            // 日期列
            const currentDate = new Date(this.startDate);
            while (currentDate <= this.endDate) {
                const dateCell = document.createElement('div');
                dateCell.className = 'gantt-cell';
                
                // 检查是否有租赁记录
                const rental = this.getRentalForDeviceAndDate(device.id, currentDate);
                if (rental) {
                    dateCell.appendChild(this.createRentalElement(rental));
                } else if (device.status === 'available') {
                    dateCell.className += ' available';
                    // 使用日期副本以避免闭包中被后续循环修改
                    const dateCopy = new Date(currentDate);
                    dateCell.onclick = () => this.handleCellClick(device, dateCopy);
                }
                
                row.appendChild(dateCell);
                currentDate.setDate(currentDate.getDate() + 1);
            }
            
            container.appendChild(row);
        });
    }
    
    createRentalElement(rental) {
        const rentalDiv = document.createElement('div');
        rentalDiv.className = 'gantt-rental';
        rentalDiv.style.width = this.calculateRentalWidth(rental) + 'px';
        
        rentalDiv.innerHTML = `
            <div class="rental-info">
                <strong>客户:</strong> ${rental.customer_name}<br>
                <strong>目的:</strong> ${rental.purpose || 'N/A'}<br>
                <strong>状态:</strong> ${this.getRentalStatusText(rental.status)}
            </div>
            <button class="delete-btn" onclick="ganttChart.deleteRental(${rental.id})">
                <i class="bi bi-trash"></i>
            </button>
            ${rental.customer_name}
        `;
        
        return rentalDiv;
    }
    
    calculateRentalWidth(rental) {
        const start = new Date(rental.start_date);
        const end = new Date(rental.end_date);
        const days = Math.ceil((end - start) / (1000 * 60 * 60 * 24)) + 1;
        return Math.max(days * 120, 120); // 最小宽度120px
    }
    
    getRentalForDeviceAndDate(deviceId, date) {
        const dateStr = this.formatDate(date);
        return this.rentals.find(rental => 
            rental.device_id === deviceId &&
            rental.start_date <= dateStr &&
            rental.end_date >= dateStr &&
            rental.status === 'active'
        );
    }
    
    handleCellClick(device, date) {
        if (!this.rentalStartDate) {
            // 第一次点击，设置开始日期
            this.rentalStartDate = date;
            this.selectedCell = event.target;
            event.target.style.backgroundColor = '#007bff';
            event.target.style.color = 'white';
            
            // 显示提示
            this.showToast('请选择结束日期', 'info');
        } else {
            // 第二次点击，设置结束日期
            const endDate = date;
            
            if (endDate < this.rentalStartDate) {
                this.showToast('结束日期不能早于开始日期', 'error');
                this.resetSelection();
                return;
            }
            
            // 打开添加租赁模态框
            this.openAddRentalModal(device, this.rentalStartDate, endDate);
            this.resetSelection();
        }
    }
    
    resetSelection() {
        if (this.selectedCell) {
            this.selectedCell.style.backgroundColor = '';
            this.selectedCell.style.color = '';
            this.selectedCell = null;
        }
        this.rentalStartDate = null;
    }
    
    openAddRentalModal(device, startDate, endDate) {
        // 填充模态框数据
        // 确保设备下拉已填充
        this.populateDeviceSelect();
        // 确保地区下拉已填充（如果初始渲染时未成功，这里兜底）
        this.ensureRegionSelectorsPopulated();
        document.getElementById('device-select').value = device.id;
        document.getElementById('start-date').value = this.formatDate(startDate);
        document.getElementById('end-date').value = this.formatDate(endDate);
        
        // 显示模态框
        const modal = new bootstrap.Modal(document.getElementById('addRentalModal'));
        modal.show();
    }
    
    async submitRental() {
        const formData = {
            device_id: document.getElementById('device-select').value,
            start_date: document.getElementById('start-date').value,
            end_date: document.getElementById('end-date').value,
            customer_name: document.getElementById('customer-name').value,
            customer_phone: document.getElementById('customer-phone').value,
            purpose: document.getElementById('purpose').value
        };
        
        try {
            const response = await axios.post('/api/rentals', formData);
            
            if (response.data.success) {
                this.showToast('租赁记录创建成功', 'success');
                
                // 关闭模态框
                const modal = bootstrap.Modal.getInstance(document.getElementById('addRentalModal'));
                modal.hide();
                
                // 刷新数据
                this.loadData();
                
                // 清空表单
                document.getElementById('addRentalForm').reset();
            } else {
                this.showToast('创建失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('创建失败: ' + error.message, 'error');
        }
    }
    
    async deleteRental(rentalId) {
        if (!confirm('确定要删除这个租赁记录吗？')) {
            return;
        }
        
        try {
            const response = await axios.delete(`/api/rentals/${rentalId}`);
            
            if (response.data.success) {
                this.showToast('租赁记录删除成功', 'success');
                this.loadData();
            } else {
                this.showToast('删除失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('删除失败: ' + error.message, 'error');
        }
    }
    
    async queryInventory() {
        const startDate = document.getElementById('query-start-date').value;
        const endDate = document.getElementById('query-end-date').value;
        const deviceType = document.getElementById('query-device-type').value;
        
        if (!startDate || !endDate) {
            this.showToast('请选择开始和结束日期', 'error');
            return;
        }
        
        try {
            const response = await axios.get('/api/inventory/available', {
                params: {
                    start_date: startDate,
                    end_date: endDate,
                    device_type: deviceType
                }
            });
            
            if (response.data.success) {
                this.displayQueryResults(response.data.data);
            } else {
                this.showToast('查询失败: ' + response.data.error, 'error');
            }
        } catch (error) {
            this.showToast('查询失败: ' + error.message, 'error');
        }
    }
    
    displayQueryResults(devices) {
        const resultsDiv = document.getElementById('query-results');
        
        if (devices.length === 0) {
            resultsDiv.innerHTML = '<div class="alert alert-info">在指定时间段内没有可用设备</div>';
            return;
        }
        
        let html = `
            <div class="alert alert-success">
                找到 ${devices.length} 台可用设备
            </div>
            <div class="table-responsive">
                <table class="table table-striped">
                    <thead>
                        <tr>
                            <th>设备名称</th>
                            <th>类型</th>
                            <th>型号</th>
                            <th>日租金</th>
                            <th>位置</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        
        devices.forEach(device => {
            html += `
                <tr>
                    <td>${device.device_name}</td>
                    <td>${device.device_type}</td>
                    <td>${device.model || 'N/A'}</td>
                    <td>¥${device.daily_rate || 'N/A'}</td>
                    <td>${device.location || 'N/A'}</td>
                </tr>
            `;
        });
        
        html += `
                    </tbody>
                </table>
            </div>
        `;
        
        resultsDiv.innerHTML = html;
    }
    
    updateStats() {
        // 更新统计信息
        document.getElementById('total-devices').textContent = this.devices.length;
        document.getElementById('available-devices').textContent = 
            this.devices.filter(d => d.status === 'available').length;
        document.getElementById('active-rentals').textContent = 
            this.rentals.filter(r => r.status === 'active').length;
        
        // 计算逾期租赁
        const today = new Date();
        const overdueCount = this.rentals.filter(r => 
            r.status === 'active' && new Date(r.end_date) < today
        ).length;
        document.getElementById('overdue-rentals').textContent = overdueCount;
    }
    
    populateFilters() {
        // 设备类型字段当前未使用，避免渲染无效选项
        const typeFilter = document.getElementById('device-type-filter');
        if (typeFilter) {
            typeFilter.innerHTML = '<option value="">全部类型</option>';
        }
        
        // 填充位置过滤器
        const locationFilter = document.getElementById('location-filter');
        const locations = [...new Set(this.devices.map(d => d.location).filter(Boolean))];
        
        locations.forEach(location => {
            const option = document.createElement('option');
            option.value = location;
            option.textContent = location;
            locationFilter.appendChild(option);
        });
        
        // 填充查询模态框的设备类型
        const queryTypeFilter = document.getElementById('query-device-type');
        if (queryTypeFilter) {
            queryTypeFilter.innerHTML = '<option value="">全部类型</option>';
        }
    }
    
    applyFilters() {
        const deviceType = document.getElementById('device-type-filter').value;
        const deviceStatus = document.getElementById('device-status-filter').value;
        const location = document.getElementById('location-filter').value;
        
        // 过滤设备
        let filteredDevices = this.devices;
        
        if (deviceType) {
            filteredDevices = filteredDevices.filter(d => d.type === deviceType);
        }
        
        if (deviceStatus) {
            filteredDevices = filteredDevices.filter(d => d.status === deviceStatus);
        }
        
        if (location) {
            filteredDevices = filteredDevices.filter(d => d.location === location);
        }
        
        // 重新渲染甘特图
        this.devices = filteredDevices;
        this.renderGantt();
    }
    
    clearFilters() {
        document.getElementById('device-type-filter').value = '';
        document.getElementById('device-status-filter').value = '';
        document.getElementById('location-filter').value = '';
        
        // 重新加载所有数据
        this.loadData();
    }
    
    navigateDate(days) {
        this.startDate.setDate(this.startDate.getDate() + days);
        this.endDate.setDate(this.endDate.getDate() + days);
        this.currentDate.setDate(this.currentDate.getDate() + days);
        
        this.updateDateNavigation();
        this.loadData();
    }
    
    goToToday() {
        const today = new Date();
        this.startDate = new Date(today.getFullYear(), today.getMonth(), 1);
        this.endDate = new Date(today.getFullYear(), today.getMonth() + 1, 0);
        this.currentDate = today;
        
        this.updateDateNavigation();
        this.loadData();
    }
    
    updateDateNavigation() {
        document.getElementById('current-period').textContent = 
            `${this.formatDate(this.startDate)} 至 ${this.formatDate(this.endDate)}`;
    }
    
    refreshData() {
        this.loadData();
    }
    
    // 工具方法
    formatDate(date) {
        // 使用本地时间，避免 toISOString 带来的时区回退（如 8 小时导致前一天）
        const y = date.getFullYear();
        const m = String(date.getMonth() + 1).padStart(2, '0');
        const d = String(date.getDate()).padStart(2, '0');
        return `${y}-${m}-${d}`;
    }
    
    isToday(date) {
        const today = new Date();
        return date.toDateString() === today.toDateString();
    }
    
    getDayName(date) {
        const days = ['日', '一', '二', '三', '四', '五', '六'];
        return days[date.getDay()];
    }

    // 如：1 日(周五)
    formatDateHeader(date) {
        const day = date.getDate();
        const week = this.getDayName(date);
        return `${day} 日(周${week})`;
    }

    // ---------------- 地区联动（省/市/区） ----------------
    initRegionSelectors() {
        // 优先使用用户提供的离线 JSON：/InventoryManager/pca-code.json
        // 结构：[{code,name,children:[{code,name,children:[{code,name}]}]}]
        const buildFromPca = (pca) => {
            const regions = {};
            pca.forEach(prov => {
                regions[prov.name] = {};
                (prov.children || []).forEach(city => {
                    regions[prov.name][city.name] = (city.children || []).map(a => a.name);
                });
            });
            return regions;
        };

        // 异步加载离线 JSON（不阻塞下拉初始化）
        this.REGIONS = {
            '北京市': { '北京市': ['东城区', '西城区', '朝阳区', '海淀区', '丰台区', '通州区'] },
            '上海市': { '上海市': ['黄浦区', '徐汇区', '长宁区', '浦东新区'] },
            '广东省': { '广州市': ['天河区', '越秀区', '荔湾区', '白云区'], '深圳市': ['南山区', '福田区', '罗湖区', '宝安区'] },
            '浙江省': { '杭州市': ['上城区', '拱墅区', '西湖区'], '宁波市': ['海曙区', '江北区'] }
        };
        // 从静态目录加载，附带时间戳避免缓存
        fetch(`/static/data/pca-code.json?t=${Date.now()}`, { cache: 'no-cache' })
            .then(res => res.ok ? res.json() : null)
            .then(pca => {
                if (!pca) return;
                this.REGIONS = buildFromPca(pca);
                // 用新数据重建三联动选项，尽量保留当前选择
                if (this.provinceSelect && this.citySelect && this.districtSelect) {
                    this.refreshRegionSelectOptions();
                }
            })
            .catch(() => {/* 静默失败，继续使用兜底数据 */});

        this.provinceSelect = document.getElementById('province-select');
        this.citySelect = document.getElementById('city-select');
        this.districtSelect = document.getElementById('district-select');

        if (!this.provinceSelect || !this.citySelect || !this.districtSelect) return;

        const fillOptions = (selectEl, items) => {
            const prev = selectEl.value;
            selectEl.innerHTML = '';
            items.forEach(v => {
                const opt = document.createElement('option');
                opt.value = v;
                opt.textContent = v;
                selectEl.appendChild(opt);
            });
            // 恢复之前的选择（如果存在）
            if (items.includes(prev)) selectEl.value = prev;
        };

        // 省份
        fillOptions(this.provinceSelect, Object.keys(this.REGIONS));

        this.provinceSelect.oninput = () => {
            const prov = this.provinceSelect.value;
            const cities = prov && this.REGIONS[prov] ? Object.keys(this.REGIONS[prov]) : [];
            fillOptions(this.citySelect, cities);
            this.citySelect.oninput();
        };

        // 城市
        this.citySelect.oninput = () => {
            const prov = this.provinceSelect.value;
            const city = this.citySelect.value;
            const dists = prov && city && this.REGIONS[prov] && this.REGIONS[prov][city] ? this.REGIONS[prov][city] : [];
            fillOptions(this.districtSelect, dists);
        };

        // 注入下拉内搜索的样式
        this.injectFilterDropdownStyles();
        // 为三个选择框增加“展开后顶部可输入搜索”的下拉
        this.attachFilterDropdown(this.provinceSelect, () => Object.keys(this.REGIONS || {}), (val) => {
            if (!val) return;
            this.provinceSelect.value = val;
            this.provinceSelect.oninput();
        });
        this.attachFilterDropdown(this.citySelect, () => {
            const prov = this.provinceSelect.value; return prov ? Object.keys(this.REGIONS[prov] || {}) : [];
        }, (val) => {
            if (!val) return;
            this.citySelect.value = val;
            this.citySelect.oninput();
        });
        this.attachFilterDropdown(this.districtSelect, () => {
            const prov = this.provinceSelect.value; const city = this.citySelect.value;
            return prov && city ? (this.REGIONS[prov][city] || []) : [];
        }, (val) => {
            if (!val) return;
            this.districtSelect.value = val;
        });

        // 初始化一次
        this.provinceSelect.oninput();

        // 在模态框打开时再次兜底填充（防止某些浏览器延迟渲染导致元素未就绪）
        const modalEl = document.getElementById('addRentalModal');
        if (modalEl) {
            modalEl.addEventListener('shown.bs.modal', () => {
                this.ensureRegionSelectorsPopulated();
            });
        }
    }

    // 填充设备下拉（新增租赁弹窗）
    populateDeviceSelect() {
        const sel = document.getElementById('device-select');
        if (!sel) return;
        const current = sel.value;
        sel.innerHTML = '<option value="">选择设备</option>';
        this.devices.forEach(d => {
            const opt = document.createElement('option');
            opt.value = d.id;
            opt.textContent = `${d.name}`;
            sel.appendChild(opt);
        });
        if (current) sel.value = current;
    }

    // 兜底保证省市区下拉有数据
    ensureRegionSelectorsPopulated() {
        this.provinceSelect = document.getElementById('province-select');
        this.citySelect = document.getElementById('city-select');
        this.districtSelect = document.getElementById('district-select');
        if (!this.provinceSelect || !this.citySelect || !this.districtSelect) return;
        if (this.provinceSelect.options.length === 0) {
            const provinces = Object.keys(this.REGIONS || {});
            if (provinces.length > 0) {
                const fill = (el, arr) => { el.innerHTML = ''; arr.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o);}); };
                fill(this.provinceSelect, provinces);
                const firstProv = this.provinceSelect.value || provinces[0];
                const cities = firstProv && this.REGIONS[firstProv] ? Object.keys(this.REGIONS[firstProv]) : [];
                fill(this.citySelect, cities);
                const firstCity = this.citySelect.value || cities[0];
                const dists = firstProv && firstCity ? (this.REGIONS[firstProv][firstCity] || []) : [];
                fill(this.districtSelect, dists);
            }
        }
    }

    // 使用当前 REGIONS 重建省/市/区选项，尽量保留原选项
    refreshRegionSelectOptions() {
        const provinces = Object.keys(this.REGIONS || {});
        const prevProv = this.provinceSelect.value;
        const prevCity = this.citySelect.value;
        const prevDist = this.districtSelect.value;

        const fill = (el, arr) => { el.innerHTML = ''; arr.forEach(v=>{const o=document.createElement('option');o.value=v;o.textContent=v;el.appendChild(o);}); };

        fill(this.provinceSelect, provinces);
        const provToUse = provinces.includes(prevProv) ? prevProv : provinces[0];
        this.provinceSelect.value = provToUse;

        const cities = provToUse && this.REGIONS[provToUse] ? Object.keys(this.REGIONS[provToUse]) : [];
        fill(this.citySelect, cities);
        const cityToUse = cities.includes(prevCity) ? prevCity : cities[0];
        this.citySelect.value = cityToUse;

        const dists = provToUse && cityToUse ? (this.REGIONS[provToUse][cityToUse] || []) : [];
        fill(this.districtSelect, dists);
        const distToUse = dists.includes(prevDist) ? prevDist : dists[0];
        this.districtSelect.value = distToUse;
    }

    // 为原生 select 附加“展开后顶部可输入搜索”的下拉浮层
    attachFilterDropdown(selectEl, getAllItems, onPick) {
        if (!selectEl) return;
        let panel = null;
        let input = null;
        let list = null;

        const closePanel = () => {
            if (panel) panel.style.display = 'none';
        };

        const openPanel = () => {
            if (!panel) {
                panel = document.createElement('div');
                panel.className = 'filter-dropdown-panel';
                panel.innerHTML = `
                    <input class="filter-input" type="text" placeholder="搜索..." />
                    <div class="filter-list" role="listbox"></div>
                `;
                selectEl.parentElement.style.position = 'relative';
                selectEl.parentElement.appendChild(panel);
                input = panel.querySelector('.filter-input');
                list = panel.querySelector('.filter-list');
                input.addEventListener('input', () => renderList());
            }
            renderList();
            panel.style.display = 'block';
            input.value = '';
            input.focus();
        };

        const renderList = () => {
            const keyword = (input?.value || '').toLowerCase();
            const items = (getAllItems() || []).filter(v => v.toLowerCase().includes(keyword));
            list.innerHTML = '';
            items.forEach(v => {
                const a = document.createElement('div');
                a.className = 'filter-item';
                a.textContent = v;
                a.onclick = () => { onPick(v); closePanel(); };
                list.appendChild(a);
            });
        };

        // 打开下拉时显示搜索面板
        selectEl.addEventListener('mousedown', (e) => {
            // 延迟到浏览器展开原生下拉后再显示我们面板
            setTimeout(openPanel, 0);
        });
        // 滚动或点击外部关闭
        document.addEventListener('click', (e) => {
            if (!panel || panel.contains(e.target) || e.target === selectEl) return;
            closePanel();
        });
    }

    injectFilterDropdownStyles() {
        if (document.getElementById('filter-dropdown-style')) return;
        const style = document.createElement('style');
        style.id = 'filter-dropdown-style';
        style.textContent = `
        .filter-dropdown-panel{position:absolute;left:0;right:0;top:100%;z-index:1051;background:#fff;border:1px solid #dee2e6;border-radius:.25rem;box-shadow:0 .5rem 1rem rgba(0,0,0,.15);}
        .filter-dropdown-panel .filter-input{width:100%;padding:.375rem .75rem;border:none;border-bottom:1px solid #dee2e6;outline:none;}
        .filter-dropdown-panel .filter-list{max-height:240px;overflow:auto;}
        .filter-dropdown-panel .filter-item{padding:.375rem .75rem;cursor:pointer;}
        .filter-dropdown-panel .filter-item:hover{background:#f8f9fa;}
        `;
        document.head.appendChild(style);
    }
    
    getStatusText(status) {
        const statusMap = {
            'available': '可用',
            'rented': '已租出',
            'maintenance': '维护中',
            'retired': '已报废'
        };
        return statusMap[status] || status;
    }
    
    getRentalStatusText(status) {
        const statusMap = {
            'pending': '待审批',
            'active': '进行中',
            'completed': '已完成',
            'cancelled': '已取消',
            'overdue': '已逾期'
        };
        return statusMap[status] || status;
    }
    
    showToast(message, type = 'info') {
        // 简单的提示实现
        const alertClass = type === 'error' ? 'alert-danger' : 
                          type === 'success' ? 'alert-success' : 'alert-info';
        
        const toast = document.createElement('div');
        toast.className = `alert ${alertClass} alert-dismissible fade show position-fixed`;
        toast.style.cssText = 'top: 20px; right: 20px; z-index: 9999; min-width: 300px;';
        toast.innerHTML = `
            ${message}
            <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
        `;
        
        document.body.appendChild(toast);
        
        // 自动消失
        setTimeout(() => {
            if (toast.parentNode) {
                toast.parentNode.removeChild(toast);
            }
        }, 5000);
    }
}

// 全局变量
let ganttChart;

// 页面加载完成后初始化
document.addEventListener('DOMContentLoaded', function() {
    ganttChart = new GanttChart();
});

// 全局函数
function navigateDate(days) {
    ganttChart.navigateDate(days);
}

function goToToday() {
    ganttChart.goToToday();
}

function refreshData() {
    ganttChart.refreshData();
}

function applyFilters() {
    ganttChart.applyFilters();
}

function clearFilters() {
    ganttChart.clearFilters();
}

function submitRental() {
    ganttChart.submitRental();
}

function queryInventory() {
    ganttChart.queryInventory();
}
